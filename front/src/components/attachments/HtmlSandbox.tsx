import React, { useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { dracula } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Code, Eye } from "lucide-react";

interface HtmlSandboxProps {
  code: string;
}

const HtmlSandbox: React.FC<HtmlSandboxProps> = ({ code }) => {
  const [showSource, setShowSource] = useState(false);

  return (
    <div
      style={{
        margin: "8px 0",
        borderRadius: 8,
        overflow: "hidden",
        border: "1px solid rgba(255,255,255,0.1)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          background: "#1e1e2e",
          padding: "4px 8px",
          gap: 4,
        }}
      >
        <button
          onClick={() => setShowSource(false)}
          style={{
            background: !showSource ? "rgba(255,255,255,0.15)" : "transparent",
            border: "none",
            color: "#ccc",
            cursor: "pointer",
            padding: "4px 8px",
            borderRadius: 4,
            display: "flex",
            alignItems: "center",
            gap: 4,
            fontSize: 12,
          }}
        >
          <Eye size={14} />
          Preview
        </button>
        <button
          onClick={() => setShowSource(true)}
          style={{
            background: showSource ? "rgba(255,255,255,0.15)" : "transparent",
            border: "none",
            color: "#ccc",
            cursor: "pointer",
            padding: "4px 8px",
            borderRadius: 4,
            display: "flex",
            alignItems: "center",
            gap: 4,
            fontSize: 12,
          }}
        >
          <Code size={14} />
          Source
        </button>
      </div>

      {showSource ? (
        <SyntaxHighlighter
          language="html"
          style={dracula}
          showLineNumbers
          wrapLines
        >
          {code}
        </SyntaxHighlighter>
      ) : (
        <iframe
          srcDoc={code}
          sandbox="allow-scripts"
          style={{
            width: "100%",
            height: "400px",
            border: "none",
            background: "#fff",
            borderRadius: "0 0 8px 8px",
          }}
          title="HTML visualization"
        />
      )}
    </div>
  );
};

export default HtmlSandbox;
