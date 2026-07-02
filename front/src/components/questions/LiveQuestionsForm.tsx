import React, { useState } from "react";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import QuestionsForm from "../QuestionsForm.tsx";
import type {
  GraphState,
  GraphTemplate,
  QuestionAnswer,
} from "../../interfaces.ts";

/**
 * Active `ask_questions` interrupt form, rendered standalone in the message flow
 * (not inside any agent run). ask_questions can be issued in parallel with other
 * tools, so its message may belong to a collapsible run — the form must stay
 * outside it. Keyed by the interrupting message id upstream so local state
 * resets between separate interrupts.
 */
const LiveQuestionsForm: React.FC<{
  thread?: UseStream<GraphState, GraphTemplate>;
}> = ({ thread }) => {
  const [handled, setHandled] = useState(false);

  const interrupt = thread?.interrupt?.value;
  const questions =
    interrupt && interrupt.type === "questions" ? interrupt.questions : undefined;

  if (!questions?.length || handled || thread?.isLoading) return null;

  const handleSubmit = (answers: QuestionAnswer[]) => {
    setHandled(true);
    thread?.submit(undefined, {
      command: { resume: { type: "questions", answers } },
      onDisconnect: "continue",
    });
  };

  const handleSkip = () => {
    setHandled(true);
    thread?.submit(undefined, {
      command: { resume: { type: "comment", message: "" } },
      onDisconnect: "continue",
    });
  };

  return (
    <div className="px-[20px]">
      <QuestionsForm
        questions={questions}
        onSubmit={handleSubmit}
        onSkip={handleSkip}
      />
    </div>
  );
};

export default LiveQuestionsForm;
