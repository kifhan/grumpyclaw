/**
 * Device test page: enumerate and test microphone, speaker, and cameras
 * (browser + grumpyreachy robot). Use before Conversation to verify hardware.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";

type MediaDeviceInfo = { deviceId: string; kind: string; label: string };

export function DeviceTestPage() {
  const [devices, setDevices] = useState<{
    mics: MediaDeviceInfo[];
    speakers: MediaDeviceInfo[];
    cameras: MediaDeviceInfo[];
    error: string | null;
  }>({ mics: [], speakers: [], cameras: [], error: null });
  const [micLevel, setMicLevel] = useState<number>(0);
  const [micStatus, setMicStatus] = useState<string>("");
  const [speakerStatus, setSpeakerStatus] = useState<string>("");
  const [cameraStatus, setCameraStatus] = useState<string>("");
  const [serverCamera, setServerCamera] = useState<{ ok: boolean; message?: string } | null>(null);
  const [robotAudioStatus, setRobotAudioStatus] = useState<{ available: boolean; message: string } | null>(null);
  const [robotSpeakerResult, setRobotSpeakerResult] = useState<{ ok: boolean; error?: string; message?: string } | null>(null);
  const [robotMicResult, setRobotMicResult] = useState<{
    ok: boolean;
    error?: string;
    message?: string;
    level?: number;
    samples?: number;
  } | null>(null);
  const [micActive, setMicActive] = useState(false);
  const [cameraActive, setCameraActive] = useState(false);

  const streamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const animationRef = useRef<number>(0);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);

  const enumerate = useCallback(async () => {
    setDevices({ mics: [], speakers: [], cameras: [], error: null });
    try {
      const list = await navigator.mediaDevices.enumerateDevices();
      const mics: MediaDeviceInfo[] = list
        .filter((d) => d.kind === "audioinput")
        .map((d) => ({ deviceId: d.deviceId, kind: d.kind, label: d.label || `Microphone ${d.deviceId.slice(0, 8)}` }));
      const speakers: MediaDeviceInfo[] = list
        .filter((d) => d.kind === "audiooutput")
        .map((d) => ({ deviceId: d.deviceId, kind: d.kind, label: d.label || `Speaker ${d.deviceId.slice(0, 8)}` }));
      const cameras: MediaDeviceInfo[] = list
        .filter((d) => d.kind === "videoinput")
        .map((d) => ({ deviceId: d.deviceId, kind: d.kind, label: d.label || `Camera ${d.deviceId.slice(0, 8)}` }));
      setDevices({ mics, speakers, cameras, error: null });
    } catch (e) {
      setDevices({
        mics: [],
        speakers: [],
        cameras: [],
        error: e instanceof Error ? e.message : "Failed to enumerate devices",
      });
    }
  }, []);

  useEffect(() => {
    enumerate();
  }, [enumerate]);

  const testMic = useCallback(async () => {
    setMicStatus("Requesting microphone…");
    stopMic();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const ctx = new AudioContext();
      audioContextRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.8;
      source.connect(analyser);
      analyserRef.current = analyser;

      const data = new Uint8Array(analyser.frequencyBinCount);

      const tick = () => {
        if (!analyserRef.current) return;
        analyserRef.current.getByteFrequencyData(data);
        const sum = data.reduce((a, b) => a + b, 0);
        const avg = sum / data.length;
        setMicLevel(avg);
        animationRef.current = requestAnimationFrame(tick);
      };
      tick();
      setMicActive(true);
      setMicStatus("Microphone active — speak to see level. Click Stop to release.");
    } catch (e) {
      setMicStatus("Error: " + (e instanceof Error ? e.message : "Permission or device failed"));
    }
  }, []);

  const stopMic = useCallback(() => {
    if (animationRef.current) cancelAnimationFrame(animationRef.current);
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    analyserRef.current = null;
    setMicLevel(0);
    setMicActive(false);
    setMicStatus("");
  }, []);

  const testSpeaker = useCallback(async () => {
    setSpeakerStatus("Playing test tone…");
    try {
      const ctx = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = 440;
      gain.gain.value = 0.2;
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.3);
      await new Promise((r) => setTimeout(r, 350));
      ctx.close();
      setSpeakerStatus("Test tone played. If you heard a short beep, speaker is working.");
    } catch (e) {
      setSpeakerStatus("Error: " + (e instanceof Error ? e.message : "AudioContext failed"));
    }
  }, []);

  const testCamera = useCallback(async () => {
    const videoEl = videoRef.current;
    if (!videoEl) return;
    setCameraStatus("Requesting camera…");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      videoEl.srcObject = stream;
      setCameraActive(true);
      setCameraStatus("Camera active — you should see yourself. Use Stop to release.");
    } catch (e) {
      setCameraStatus("Error: " + (e instanceof Error ? e.message : "Permission or device failed"));
    }
  }, []);

  const stopCamera = useCallback(() => {
    const videoEl = videoRef.current;
    if (videoEl && videoEl.srcObject) {
      const s = videoEl.srcObject as MediaStream;
      s.getTracks().forEach((t) => t.stop());
      videoEl.srcObject = null;
    }
    setCameraActive(false);
    setCameraStatus("");
  }, []);

  useEffect(() => {
    return () => stopMic();
  }, [stopMic]);

  const checkServerCamera = useCallback(async () => {
    setServerCamera(null);
    try {
      const data = await api.devicesCamera();
      setServerCamera(data);
    } catch (e) {
      setServerCamera({ ok: false, message: e instanceof Error ? e.message : "Request failed" });
    }
  }, []);

  const loadRobotAudioStatus = useCallback(async () => {
    try {
      const data = await api.devicesAudioStatus();
      setRobotAudioStatus(data);
    } catch {
      setRobotAudioStatus({ available: false, message: "API unavailable" });
    }
  }, []);

  const testRobotSpeaker = useCallback(async () => {
    setRobotSpeakerResult(null);
    try {
      const data = await api.devicesAudioTestSpeaker();
      setRobotSpeakerResult(data);
    } catch (e) {
      setRobotSpeakerResult({ ok: false, error: e instanceof Error ? e.message : "Request failed" });
    }
  }, []);

  const testRobotMic = useCallback(async () => {
    setRobotMicResult(null);
    try {
      const data = await api.devicesAudioTestMic();
      setRobotMicResult(data);
    } catch (e) {
      setRobotMicResult({ ok: false, error: e instanceof Error ? e.message : "Request failed" });
    }
  }, []);

  useEffect(() => {
    loadRobotAudioStatus();
  }, [loadRobotAudioStatus]);

  return (
    <div>
      <h2>Device test</h2>
      <p className="panel" style={{ marginBottom: 16 }}>
        Test microphone, speaker, and cameras before using Conversation. Enumerated devices are from this browser.
      </p>

      <div className="panel">
        <h4>Devices</h4>
        <button onClick={enumerate}>Refresh device list</button>
        {devices.error && <p style={{ color: "var(--color-error, #c00)" }}>{devices.error}</p>}
        <dl style={{ marginTop: 8 }}>
          <dt>Microphones ({devices.mics.length})</dt>
          <dd>{devices.mics.length ? devices.mics.map((d) => d.label).join(", ") : "None or no permission"}</dd>
          <dt>Speakers ({devices.speakers.length})</dt>
          <dd>{devices.speakers.length ? devices.speakers.map((d) => d.label).join(", ") : "None"}</dd>
          <dt>Cameras ({devices.cameras.length})</dt>
          <dd>{devices.cameras.length ? devices.cameras.map((d) => d.label).join(", ") : "None or no permission"}</dd>
        </dl>
      </div>

      <div className="panel">
        <h4>Microphone test</h4>
        <div className="row">
          <button onClick={testMic} disabled={micActive}>
            Start mic test
          </button>
          <button onClick={stopMic}>Stop</button>
        </div>
        {micLevel > 0 && (
          <div style={{ marginTop: 8 }}>
            <div
              style={{
                height: 24,
                background: "#333",
                borderRadius: 4,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${Math.min(100, (micLevel / 128) * 100)}%`,
                  height: "100%",
                  background: "var(--color-accent, #0a7)",
                  transition: "width 0.05s",
                }}
              />
            </div>
            <small>Level: {micLevel}</small>
          </div>
        )}
        {micStatus && <p style={{ marginTop: 8 }}>{micStatus}</p>}
      </div>

      <div className="panel">
        <h4>Speaker test</h4>
        <button onClick={testSpeaker}>Play test tone (440 Hz, 0.3 s)</button>
        {speakerStatus && <p style={{ marginTop: 8 }}>{speakerStatus}</p>}
      </div>

      <div className="panel">
        <h4>Camera test (browser)</h4>
        <div className="row">
          <button onClick={testCamera} disabled={cameraActive}>
            Start camera
          </button>
          <button onClick={stopCamera}>Stop camera</button>
        </div>
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          style={{ maxWidth: "100%", maxHeight: 240, background: "#000", marginTop: 8 }}
        />
        {cameraStatus && <p style={{ marginTop: 8 }}>{cameraStatus}</p>}
      </div>

      <div className="panel">
        <h4>grumpyreachy speaker &amp; mic (robot)</h4>
        <p>Test the Reachy Mini&apos;s speaker and microphone on the machine running the API. Start the robot first (Runtime or autostart).</p>
        <button onClick={loadRobotAudioStatus}>Refresh status</button>
        {robotAudioStatus && (
          <p style={{ marginTop: 8 }}>
            {robotAudioStatus.available ? "Ready — " + robotAudioStatus.message : robotAudioStatus.message}
          </p>
        )}
        <div className="row" style={{ marginTop: 8 }}>
          <button onClick={testRobotSpeaker} disabled={!robotAudioStatus?.available}>
            Test robot speaker
          </button>
          <button onClick={testRobotMic} disabled={!robotAudioStatus?.available}>
            Test robot mic
          </button>
        </div>
        {robotSpeakerResult && (
          <p style={{ marginTop: 8 }}>
            Speaker: {robotSpeakerResult.ok ? "OK — " + (robotSpeakerResult.message ?? "Tone played") : "Failed — " + (robotSpeakerResult.error ?? "")}
          </p>
        )}
        {robotMicResult && (
          <p style={{ marginTop: 8 }}>
            Mic: {robotMicResult.ok
              ? "OK — " + (robotMicResult.message ?? `level=${robotMicResult.level ?? "?"}, samples=${robotMicResult.samples ?? "?"}`)
              : "Failed — " + (robotMicResult.error ?? "")}
          </p>
        )}
      </div>

      <div className="panel">
        <h4>Server-side camera (grumpyreachy)</h4>
        <p>Check if the robot app has a camera frame (e.g. on the machine running the API).</p>
        <button onClick={checkServerCamera}>Check server camera</button>
        {serverCamera && (
          <p style={{ marginTop: 8 }}>
            {serverCamera.ok ? "OK — " + (serverCamera.message || "Camera available") : "Failed — " + (serverCamera.message || "Not available")}
          </p>
        )}
      </div>
    </div>
  );
}
