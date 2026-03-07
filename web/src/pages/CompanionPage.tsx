import { useEffect, useState } from "react";
import { api, makeSse } from "../api";

type TriggerName = "looked_at" | "called" | "petted" | "idle_heartbeat";
type ReactionType = "play_emotion" | "dance";
type PatrolDirection = "front" | "left" | "right" | "up" | "down";

type TriggerConfig = {
  enabled: boolean;
  cooldown_seconds: number;
  allowed_reaction_types: ReactionType[];
};

type CompanionConfig = {
  enabled: boolean;
  idle_interval_seconds: number;
  wake_phrases: string[];
  queue_policy: "queue_next";
  patrol_enabled: boolean;
  patrol_start_after_seconds: number;
  patrol_scan_pattern: PatrolDirection[];
  patrol_step_duration_seconds: number;
  look_dwell_ms: number;
  triggers: Record<TriggerName, TriggerConfig>;
};

const triggerLabels: Array<[TriggerName, string]> = [
  ["looked_at", "Person looked at robot"],
  ["called", "Person called robot"],
  ["petted", "Robot head petted"],
  ["idle_heartbeat", "Idle heartbeat"],
];

const defaultConfig: CompanionConfig = {
  enabled: true,
  idle_interval_seconds: 90,
  wake_phrases: ["grumpy", "grumpyclaw", "reachy"],
  queue_policy: "queue_next",
  patrol_enabled: true,
  patrol_start_after_seconds: 20,
  patrol_scan_pattern: ["front", "left", "right", "up", "front"],
  patrol_step_duration_seconds: 1,
  look_dwell_ms: 1200,
  triggers: {
    looked_at: { enabled: true, cooldown_seconds: 8, allowed_reaction_types: ["play_emotion"] },
    called: { enabled: true, cooldown_seconds: 5, allowed_reaction_types: ["play_emotion"] },
    petted: { enabled: true, cooldown_seconds: 4, allowed_reaction_types: ["play_emotion"] },
    idle_heartbeat: { enabled: true, cooldown_seconds: 90, allowed_reaction_types: ["play_emotion", "dance"] },
  },
};

function normalizeReactionTypes(value: unknown, fallback: ReactionType[]): ReactionType[] {
  if (!Array.isArray(value)) return fallback;
  const out = value.filter((item): item is ReactionType => item === "play_emotion" || item === "dance");
  return out.length > 0 ? out : fallback;
}

function normalizeConfig(raw: Record<string, unknown> | null | undefined): CompanionConfig {
  const input = raw ?? {};
  const triggersRaw = (input.triggers ?? {}) as Record<string, Record<string, unknown>>;
  return {
    enabled: Boolean(input.enabled ?? defaultConfig.enabled),
    idle_interval_seconds: Number(input.idle_interval_seconds ?? defaultConfig.idle_interval_seconds),
    wake_phrases: Array.isArray(input.wake_phrases)
      ? input.wake_phrases.map((item) => String(item)).filter(Boolean)
      : defaultConfig.wake_phrases,
    queue_policy: "queue_next",
    patrol_enabled: Boolean(input.patrol_enabled ?? defaultConfig.patrol_enabled),
    patrol_start_after_seconds: Number(
      input.patrol_start_after_seconds ?? defaultConfig.patrol_start_after_seconds,
    ),
    patrol_scan_pattern: Array.isArray(input.patrol_scan_pattern)
      ? input.patrol_scan_pattern.map((item) => String(item) as PatrolDirection).filter(Boolean)
      : defaultConfig.patrol_scan_pattern,
    patrol_step_duration_seconds: Number(
      input.patrol_step_duration_seconds ?? defaultConfig.patrol_step_duration_seconds,
    ),
    look_dwell_ms: Number(input.look_dwell_ms ?? defaultConfig.look_dwell_ms),
    triggers: {
      looked_at: {
        enabled: Boolean(triggersRaw.looked_at?.enabled ?? defaultConfig.triggers.looked_at.enabled),
        cooldown_seconds: Number(
          triggersRaw.looked_at?.cooldown_seconds ?? defaultConfig.triggers.looked_at.cooldown_seconds,
        ),
        allowed_reaction_types: normalizeReactionTypes(
          triggersRaw.looked_at?.allowed_reaction_types,
          defaultConfig.triggers.looked_at.allowed_reaction_types,
        ),
      },
      called: {
        enabled: Boolean(triggersRaw.called?.enabled ?? defaultConfig.triggers.called.enabled),
        cooldown_seconds: Number(
          triggersRaw.called?.cooldown_seconds ?? defaultConfig.triggers.called.cooldown_seconds,
        ),
        allowed_reaction_types: normalizeReactionTypes(
          triggersRaw.called?.allowed_reaction_types,
          defaultConfig.triggers.called.allowed_reaction_types,
        ),
      },
      petted: {
        enabled: Boolean(triggersRaw.petted?.enabled ?? defaultConfig.triggers.petted.enabled),
        cooldown_seconds: Number(
          triggersRaw.petted?.cooldown_seconds ?? defaultConfig.triggers.petted.cooldown_seconds,
        ),
        allowed_reaction_types: normalizeReactionTypes(
          triggersRaw.petted?.allowed_reaction_types,
          defaultConfig.triggers.petted.allowed_reaction_types,
        ),
      },
      idle_heartbeat: {
        enabled: Boolean(triggersRaw.idle_heartbeat?.enabled ?? defaultConfig.triggers.idle_heartbeat.enabled),
        cooldown_seconds: Number(
          triggersRaw.idle_heartbeat?.cooldown_seconds ?? defaultConfig.triggers.idle_heartbeat.cooldown_seconds,
        ),
        allowed_reaction_types: normalizeReactionTypes(
          triggersRaw.idle_heartbeat?.allowed_reaction_types,
          defaultConfig.triggers.idle_heartbeat.allowed_reaction_types,
        ),
      },
    },
  };
}

function toggleReactionType(list: ReactionType[], value: ReactionType): ReactionType[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

function statusTone(status: string): string {
  if (status === "available") return "badge ok";
  if (status === "degraded") return "badge warn";
  return "badge off";
}

export function CompanionPage() {
  const [draft, setDraft] = useState<CompanionConfig>(defaultConfig);
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [events, setEvents] = useState<Array<Record<string, unknown>>>([]);
  const [saveState, setSaveState] = useState("");
  const [busyTrigger, setBusyTrigger] = useState<TriggerName | null>(null);

  async function refresh() {
    const [configRes, statusRes, eventsRes] = await Promise.all([
      api.companionConfig(),
      api.companionStatus(),
      api.companionEvents(40),
    ]);
    setDraft(normalizeConfig(configRes));
    setStatus(statusRes);
    setEvents(eventsRes);
  }

  useEffect(() => {
    refresh().catch(console.error);
    const stream = makeSse("/companion/events/stream");
    const handler = () => {
      api.companionStatus().then(setStatus).catch(console.error);
      api.companionEvents(40).then(setEvents).catch(console.error);
    };
    const eventTypes = [
      "companion.trigger_detected",
      "companion.reaction_selected",
      "companion.reaction_queued",
      "companion.reaction_executed",
      "companion.detector_status",
      "companion.patrol_started",
      "companion.patrol_step",
      "companion.person_found",
      "companion.patrol_stopped",
    ];
    eventTypes.forEach((eventType) => stream.addEventListener(eventType, handler));
    return () => stream.close();
  }, []);

  function patchTrigger(trigger: TriggerName, patch: Partial<TriggerConfig>) {
    setDraft((current) => ({
      ...current,
      triggers: {
        ...current.triggers,
        [trigger]: {
          ...current.triggers[trigger],
          ...patch,
        },
      },
    }));
  }

  async function saveConfig() {
    setSaveState("Saving...");
    try {
      await api.companionUpdateConfig(draft as unknown as Record<string, unknown>);
      setSaveState("Saved");
      await refresh();
    } catch (error) {
      setSaveState(error instanceof Error ? error.message : "Save failed");
    }
  }

  async function simulate(trigger: TriggerName) {
    setBusyTrigger(trigger);
    try {
      await api.companionSimulate(trigger);
      await refresh();
    } finally {
      setBusyTrigger(null);
    }
  }

  const detectors = (status?.detectors ?? {}) as Record<string, Record<string, unknown>>;
  const patrol = (status?.patrol ?? {}) as Record<string, unknown>;
  const queue = (status?.queue ?? {}) as Record<string, unknown>;

  return (
    <div>
      <h2>Companion</h2>

      <div className="companion-grid">
        <section className="panel">
          <h4>Behavior Config</h4>
          <div className="field-grid">
            <label className="field">
              <span>Enable subsystem</span>
              <input
                type="checkbox"
                checked={draft.enabled}
                onChange={(e) => setDraft((current) => ({ ...current, enabled: e.target.checked }))}
              />
            </label>

            <label className="field">
              <span>Wake phrases</span>
              <input
                value={draft.wake_phrases.join(", ")}
                onChange={(e) =>
                  setDraft((current) => ({
                    ...current,
                    wake_phrases: e.target.value
                      .split(",")
                      .map((item) => item.trim().toLowerCase())
                      .filter(Boolean),
                  }))
                }
              />
            </label>

            <label className="field">
              <span>Look dwell (ms)</span>
              <input
                type="number"
                value={draft.look_dwell_ms}
                onChange={(e) =>
                  setDraft((current) => ({ ...current, look_dwell_ms: Number(e.target.value) || 0 }))
                }
              />
            </label>

            <label className="field">
              <span>Idle heartbeat interval (s)</span>
              <input
                type="number"
                value={draft.idle_interval_seconds}
                onChange={(e) =>
                  setDraft((current) => ({ ...current, idle_interval_seconds: Number(e.target.value) || 0 }))
                }
              />
            </label>

            <label className="field">
              <span>Enable patrol</span>
              <input
                type="checkbox"
                checked={draft.patrol_enabled}
                onChange={(e) => setDraft((current) => ({ ...current, patrol_enabled: e.target.checked }))}
              />
            </label>

            <label className="field">
              <span>Patrol start after (s)</span>
              <input
                type="number"
                value={draft.patrol_start_after_seconds}
                onChange={(e) =>
                  setDraft((current) => ({
                    ...current,
                    patrol_start_after_seconds: Number(e.target.value) || 0,
                  }))
                }
              />
            </label>

            <label className="field">
              <span>Patrol scan pattern</span>
              <input
                value={draft.patrol_scan_pattern.join(", ")}
                onChange={(e) =>
                  setDraft((current) => ({
                    ...current,
                    patrol_scan_pattern: e.target.value
                      .split(",")
                      .map((item) => item.trim().toLowerCase() as PatrolDirection)
                      .filter(Boolean),
                  }))
                }
              />
            </label>

            <label className="field">
              <span>Patrol step duration (s)</span>
              <input
                type="number"
                step="0.1"
                value={draft.patrol_step_duration_seconds}
                onChange={(e) =>
                  setDraft((current) => ({
                    ...current,
                    patrol_step_duration_seconds: Number(e.target.value) || 0,
                  }))
                }
              />
            </label>
          </div>

          <div className="trigger-config-list">
            {triggerLabels.map(([trigger, label]) => (
              <div key={trigger} className="trigger-card">
                <strong>{label}</strong>
                <label className="field">
                  <span>Enabled</span>
                  <input
                    type="checkbox"
                    checked={draft.triggers[trigger].enabled}
                    onChange={(e) => patchTrigger(trigger, { enabled: e.target.checked })}
                  />
                </label>
                <label className="field">
                  <span>Cooldown (s)</span>
                  <input
                    type="number"
                    value={draft.triggers[trigger].cooldown_seconds}
                    onChange={(e) =>
                      patchTrigger(trigger, { cooldown_seconds: Number(e.target.value) || 0 })
                    }
                  />
                </label>
                <div className="row">
                  <label>
                    <input
                      type="checkbox"
                      checked={draft.triggers[trigger].allowed_reaction_types.includes("play_emotion")}
                      onChange={() =>
                        patchTrigger(trigger, {
                          allowed_reaction_types: toggleReactionType(
                            draft.triggers[trigger].allowed_reaction_types,
                            "play_emotion",
                          ),
                        })
                      }
                    />
                    Emotion
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={draft.triggers[trigger].allowed_reaction_types.includes("dance")}
                      onChange={() =>
                        patchTrigger(trigger, {
                          allowed_reaction_types: toggleReactionType(
                            draft.triggers[trigger].allowed_reaction_types,
                            "dance",
                          ),
                        })
                      }
                    />
                    Dance
                  </label>
                </div>
              </div>
            ))}
          </div>

          <div className="row">
            <button onClick={saveConfig}>Save Config</button>
            <span className="muted">{saveState}</span>
          </div>
        </section>

        <section className="panel">
          <h4>Live Status</h4>
          <div className="row">
            <span className="badge">{String(status?.idle_mode ?? "unknown")}</span>
            <span className={Boolean(status?.conversation_active) ? "badge warn" : "badge ok"}>
              conversation {Boolean(status?.conversation_active) ? "active" : "idle"}
            </span>
            <span className={Boolean((patrol.active as boolean | undefined) ?? false) ? "badge warn" : "badge ok"}>
              patrol {Boolean((patrol.active as boolean | undefined) ?? false) ? "active" : "stopped"}
            </span>
          </div>

          <div className="status-stack">
            <div>
              <strong>Queued reaction</strong>
              <pre>{JSON.stringify(queue.queued_reaction ?? null, null, 2)}</pre>
            </div>
            <div>
              <strong>Active reaction</strong>
              <pre>{JSON.stringify(queue.active_reaction ?? null, null, 2)}</pre>
            </div>
            <div>
              <strong>Latest trigger</strong>
              <pre>{JSON.stringify(status?.latest_trigger ?? null, null, 2)}</pre>
            </div>
            <div>
              <strong>Latest executed reaction</strong>
              <pre>{JSON.stringify(status?.latest_executed_reaction ?? null, null, 2)}</pre>
            </div>
          </div>
        </section>
      </div>

      <div className="companion-grid">
        <section className="panel">
          <h4>Detectors</h4>
          <div className="detector-list">
            {Object.entries(detectors).map(([name, detector]) => (
              <div key={name} className="detector-card">
                <div className="row">
                  <strong>{name}</strong>
                  <span className={statusTone(String(detector.status ?? "unavailable"))}>
                    {String(detector.status ?? "unknown")}
                  </span>
                </div>
                <p className="muted">{String(detector.detail ?? "")}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <h4>Simulate Triggers</h4>
          <div className="row">
            {triggerLabels.map(([trigger, label]) => (
              <button key={trigger} onClick={() => simulate(trigger)} disabled={busyTrigger === trigger}>
                {busyTrigger === trigger ? "Running..." : label}
              </button>
            ))}
          </div>
        </section>

        <section className="panel">
          <h4>Patrol Snapshot</h4>
          <pre>{JSON.stringify(patrol, null, 2)}</pre>
        </section>
      </div>

      <section className="panel">
        <h4>Recent Events</h4>
        <div className="event-list">
          {events.map((item) => {
            const eventType = String(item.event_type ?? "event");
            const payload = item.payload ?? null;
            const key = `${String(item.id ?? eventType)}-${String(item.created_at ?? "")}`;
            return (
              <div key={key} className="event-card">
                <div className="row">
                  <strong>{eventType}</strong>
                  <span className="muted">{String(item.created_at ?? "")}</span>
                </div>
                <pre>{JSON.stringify(payload, null, 2)}</pre>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
