import { useEffect } from "react";
import { Message as Message_ } from "@langchain/langgraph-sdk";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState, GraphTemplate } from "../interfaces.ts";
import { useBranches } from "@/hooks/useBranches";
import { ChevronLeft, ChevronRight } from "lucide-react";

export function BranchSwitcher({
  thread,
  message,
}: {
  thread?: UseStream<GraphState, GraphTemplate>;
  message: Message_;
}) {
  const branches = useBranches();
  useEffect(() => {
    void branches.ensureTree();
  }, [branches.ensureTree]);
  const { branch, branchOptions, index } =
    branches.getMessageBranchInfo(message);
  if (!branchOptions || !branch || branchOptions.length <= 1) return null;
  const onSelect = (b: string) => branches.switchBranch(b);

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() => {
          const prevBranch = branchOptions[index - 1];
          if (!prevBranch) return;
          onSelect(prevBranch);
        }}
        disabled={thread?.isLoading}
        className="transition-transform duration-200 bg-transparent border-0 text-foreground p-0 disabled:opacity-50 cursor-pointer hover:scale-110 disabled:hover:scale-100"
      >
        <ChevronLeft size={16} />
      </button>
      <span className="text-[13px]">
        {index + 1} / {branchOptions.length}
      </span>
      <button
        onClick={() => {
          const nextBranch = branchOptions[index + 1];
          if (!nextBranch) return;
          onSelect(nextBranch);
        }}
        disabled={thread?.isLoading}
        className="transition-transform duration-200 bg-transparent border-0 text-foreground p-0 disabled:opacity-50 cursor-pointer hover:scale-110 disabled:hover:scale-100"
      >
        <ChevronRight size={16} />
      </button>
    </div>
  );
}
