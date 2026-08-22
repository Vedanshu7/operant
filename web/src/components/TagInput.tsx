import { useId, useState, type KeyboardEvent, type ReactElement } from "react";

export interface TagInputProps {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
}

export function TagInput({ label, values, onChange, placeholder }: TagInputProps): ReactElement {
  const [draft, setDraft] = useState("");
  const id = useId();

  const commit = (): void => {
    const v = draft.trim();
    if (v && !values.includes(v)) onChange([...values, v]);
    setDraft("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>): void => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commit();
    } else if (e.key === "Backspace" && draft === "" && values.length > 0) {
      onChange(values.slice(0, -1));
    }
  };

  return (
    <div>
      <label className="label" htmlFor={id}>
        {label}
      </label>
      <div className="input flex flex-wrap items-center gap-1">
        {values.map((v) => (
          <span
            key={v}
            className="inline-flex items-center gap-1 rounded bg-zinc-200 px-1.5 py-0.5 font-mono text-xs dark:bg-zinc-700"
          >
            {v}
            <button
              type="button"
              aria-label={`Remove ${v}`}
              className="text-muted-foreground hover:text-red-600"
              onClick={() => onChange(values.filter((x) => x !== v))}
            >
              ×
            </button>
          </span>
        ))}
        <input
          id={id}
          className="min-w-[8rem] flex-1 bg-transparent text-sm outline-none"
          value={draft}
          placeholder={placeholder ?? "Type and press Enter"}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={commit}
        />
      </div>
    </div>
  );
}
