import React, { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";
import { useDarkMode } from "@/hooks/use-dark-mode.tsx";

let mermaidCounter = 0;

interface MermaidDiagramProps {
  chart: string;
}

const MermaidDiagram: React.FC<MermaidDiagramProps> = ({ chart }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string>("");
  const idRef = useRef(`mermaid-${Date.now()}-${mermaidCounter++}`);
  const isDarkMode = useDarkMode();

  useEffect(() => {
    let cancelled = false;

    const render = async () => {
      try {
        mermaid.initialize({
          startOnLoad: false,
          theme: isDarkMode ? "dark" : "default",
          securityLevel: "loose",
        });
        const { svg: renderedSvg } = await mermaid.render(idRef.current, chart);
        if (!cancelled) {
          setSvg(renderedSvg);
          setError("");
        }
      } catch (e: any) {
        if (!cancelled) {
          setError(e?.message || "Failed to render mermaid diagram");
          setSvg("");
        }
      }
    };

    render();
    return () => {
      cancelled = true;
    };
  }, [chart, isDarkMode]);

  if (error) {
    return (
      <div
        style={{
          background: isDarkMode ? "#2d2d2d" : "#fdecea",
          borderRadius: 8,
          padding: "12px 16px",
          margin: "8px 0",
          color: isDarkMode ? "#ff6b6b" : "#b42318",
          fontSize: 14,
          fontFamily: "monospace",
          whiteSpace: "pre-wrap",
        }}
      >
        Mermaid error: {error}
        <pre
          style={{
            color: isDarkMode ? "#ccc" : "#444",
            marginTop: 8,
          }}
        >
          {chart}
        </pre>
      </div>
    );
  }

  return (
    <div
      style={{
        margin: "8px 0",
        overflow: "auto",
        background: isDarkMode ? "#1e1e2e" : "#ffffff",
        borderRadius: 8,
        padding: 16,
      }}
    >
      <div
        ref={containerRef}
        style={{
          width: "max-content",
          minWidth: "100%",
          display: "flex",
          justifyContent: "center",
        }}
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    </div>
  );
};

export default MermaidDiagram;
