import { useState, type FormEvent, type ReactElement } from "react";

import { useAnswerClarification } from "@/api/queries";
import type { Clarification } from "@/api/types";
import { formatTime } from "@/lib/format";

import { Button } from "./Button";
import { Card } from "./Card";
import { ErrorBox } from "./ErrorBox";

export interface ClarificationCardProps {
  clarification: Clarification;
}

export function ClarificationCard({ clarification }: ClarificationCardProps): ReactElement {
  const [answer, setAnswer] = useState("");
  const reply = useAnswerClarification();
  const submit = (e: FormEvent): void => {
    e.preventDefault();
    if (answer.trim() === "") return;
    reply.mutate({ id: clarification.id, answer: answer.trim() });
  };
  return (
    <Card title="The agent has a question" className="border-violet-300 dark:border-violet-700">
      <form onSubmit={submit} className="space-y-3">
        <p className="text-sm font-medium">{clarification.question}</p>
        <p className="text-xs text-muted-foreground">asked {formatTime(clarification.raised_at)}</p>
        <textarea
          aria-label="Answer"
          className="input"
          rows={3}
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="Your answer"
        />
        <ErrorBox error={reply.error} />
        <Button type="submit" variant="primary" disabled={reply.isPending || answer.trim() === ""}>
          Send answer
        </Button>
      </form>
    </Card>
  );
}
