import React, { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";

mermaid.initialize({
  startOnLoad: false,
  theme: "dark",
  securityLevel: "loose",
});

let mermaidCounter = 0;

interface MermaidDiagramProps {
  chart: string;
}

const MermaidDiagram: React.FC<MermaidDiagramProps> = ({ chart }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string>("");
  const idRef = useRef(`mermaid-${Date.now()}-${mermaidCounter++}`);

  useEffect(() => {
    let cancelled = false;

    const render = async () => {
      try {
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
  }, [chart]);

  if (error) {
    return (
      <div
        style={{
          background: "#2d2d2d",
          borderRadius: 8,
          padding: "12px 16px",
          margin: "8px 0",
          color: "#ff6b6b",
          fontSize: 14,
          fontFamily: "monospace",
          whiteSpace: "pre-wrap",
        }}
      >
        Mermaid error: {error}
        <pre style={{ color: "#ccc", marginTop: 8 }}>{chart}</pre>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      style={{
        margin: "8px 0",
        overflow: "auto",
        background: "#1e1e2e",
        borderRadius: 8,
        padding: 16,
      }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
};

export default MermaidDiagram;
