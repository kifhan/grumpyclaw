import { useEffect, useState } from "react";
import { api } from "../api";

export function SkillsPage() {
  const [skills, setSkills] = useState<Array<{ id: string; name: string; preview: string }>>([]);
  const [output, setOutput] = useState("");

  async function refresh() {
    setSkills(await api.listSkills());
  }

  useEffect(() => {
    refresh().catch(console.error);
  }, []);

  async function run(skillId: string) {
    const out = await api.runSkill(skillId);
    setOutput(out.content);
  }

  return (
    <div>
      <h2>Skills</h2>
      <div className="row">
        <div className="panel" style={{ width: 420 }}>
          {skills.map((s) => (
            <div key={s.id} className="panel">
              <b>{s.name}</b>
              <div>{s.id}</div>
              <p>{s.preview}</p>
              <button onClick={() => run(s.id)}>Run</button>
            </div>
          ))}
        </div>
        <div className="panel" style={{ flex: 1 }}>
          <h4>Skill Output</h4>
          <pre>{output}</pre>
        </div>
      </div>
    </div>
  );
}
