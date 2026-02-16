"""Terminal chat: REPL with LLM, optional memory retrieval and skills in context."""

from __future__ import annotations

import sys


def _build_system_prompt() -> str:
    parts = [
        "You are a helpful personal AI assistant. Use the provided context (memory, skills) when relevant.",
    ]
    try:
        from grumpyclaw.skills.registry import list_skills
        skills = list_skills()
        if skills:
            parts.append("\n\nAvailable skills (use when relevant):\n")
            for s in skills:
                parts.append(f"\n--- {s['name']} ---\n{s['content']}\n")
    except Exception:
        pass
    return "\n".join(parts).strip()


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from grumpyclaw.llm.client import chat
    from grumpyclaw.memory.retriever import Retriever

    system = _build_system_prompt()
    retriever = Retriever()
    messages: list[dict] = [{"role": "system", "content": system}]

    print("Terminal chat (grumpyClaw). /quit to exit, /clear to reset history.")
    while True:
        try:
            user_input = input("You: ").strip()
        except EOFError:
            break
        if not user_input:
            continue
        if user_input.lower() in ("/quit", "/exit", "/q"):
            break
        if user_input.lower() == "/clear":
            messages = [{"role": "system", "content": system}]
            print("History cleared.")
            continue

        # Optional: inject retrieved context
        try:
            hits = retriever.hybrid_search(user_input, top_k=5)
            if hits:
                context = "\n".join(
                    f"[{h['title']}] {h['content'][:300]}..."
                    if len(h.get("content", "")) > 300
                    else f"[{h['title']}] {h['content']}"
                    for h in hits
                )
                user_with_context = f"Relevant context from memory:\n{context}\n\nUser: {user_input}"
            else:
                user_with_context = user_input
        except Exception:
            user_with_context = user_input

        messages.append({"role": "user", "content": user_with_context})
        try:
            reply = chat(messages)
        except Exception as e:
            print("Error:", e, file=sys.stderr)
            messages.pop()
            continue
        messages.append({"role": "assistant", "content": reply})
        print("Assistant:", reply)

    return 0


if __name__ == "__main__":
    sys.exit(main())
