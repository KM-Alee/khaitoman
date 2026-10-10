/**
 * The Ask box (docs/WIN_PLAN.md W5): the assistant as the front door. Submitting opens the
 * seeded watercourse on its saved plan and hands the question to the copilot, which answers
 * live with the real tools (and reuses the saved frontier and stress analyses).
 */
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { ArrowUp, MessagesSquare } from "lucide-react";
import { useHeadline } from "@/lib/api/showcase";
import { useUI } from "@/app/store";
import { cn } from "@/lib/cn";

export const ASK_CHIPS: { text: string; lang?: "ur" }[] = [
  { text: "Is the integrated plan fair to tail farmers?" },
  { text: "What happens in a dry year with a water cut?" },
  { text: "اگر نہر دو ہفتے بند رہے تو کیا ہوگا؟", lang: "ur" },
];

export function AskBox({ fallbackHref, className }: { fallbackHref?: string | null; className?: string }) {
  const h = useHeadline();
  const set = useUI((s) => s.set);
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const href = h.data
    ? `/p/${encodeURIComponent(h.data.pilot_id)}/${encodeURIComponent(h.data.pilot_version)}/workspace?run=${encodeURIComponent(h.data.plans.P.run_id)}`
    : (fallbackHref ?? null);
  const ask = (q: string) => {
    const m = q.trim();
    if (!m || !href) return;
    set({ assistantOpen: true, assistantDraft: { text: m, autoSend: true } });
    navigate(href);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    ask(text);
  };
  return (
    <div className={cn("flex flex-col gap-3", className)} data-testid="ask-box">
      <form onSubmit={submit} className="flex items-center gap-2 rounded-[20px] border border-border-strong/40 bg-surface-raised p-2 pl-4 shadow-2 focus-within:border-water focus-within:shadow-glow">
        <MessagesSquare size={20} className="shrink-0 text-water" aria-hidden />
        <label htmlFor="landing-ask" className="sr-only">
          Ask AabFlow anything
        </label>
        <input
          id="landing-ask"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Ask AabFlow anything…"
          dir="auto"
          className="min-w-0 flex-1 bg-transparent py-2.5 text-[16px] text-ink outline-none placeholder:text-ink-tertiary"
          data-testid="ask-input"
        />
        <button
          type="submit"
          disabled={!text.trim() || !href}
          className="grid h-11 w-11 shrink-0 place-items-center rounded-[14px] bg-water text-white transition-colors hover:bg-water-deep disabled:opacity-40"
          aria-label="Ask"
          data-testid="ask-submit"
        >
          <ArrowUp size={19} aria-hidden />
        </button>
      </form>
      <ul className="flex flex-wrap gap-2" aria-label="Example questions">
        {ASK_CHIPS.map((c) => (
          <li key={c.text}>
            <button
              type="button"
              onClick={() => ask(c.text)}
              disabled={!href}
              lang={c.lang}
              dir="auto"
              className={cn(
                "rounded-full border border-border bg-surface px-3.5 py-1.5 text-[13px] text-ink-secondary shadow-1 transition-colors hover:border-water/40 hover:text-water-deep disabled:opacity-50",
                c.lang === "ur" && "urdu text-[15px]",
              )}
              data-testid="ask-chip"
            >
              {c.text}
            </button>
          </li>
        ))}
      </ul>
      <p className="text-[12px] text-ink-tertiary">Answers live in about 10–30 s, in English or Urdu, using the app's real tools. It needs the internet; planning doesn't.</p>
    </div>
  );
}
