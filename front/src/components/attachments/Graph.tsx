import React, { useEffect, useMemo, useState } from "react";
import { useDarkMode } from "@/hooks/use-dark-mode.tsx";
import styled from "styled-components";
import { useSelectedAttachments } from "../../hooks/SelectedAttachmentsContext.tsx";
import { Check } from "lucide-react";
// @ts-ignore
import Plot from "react-plotly.js";
import { apiClient } from "@/lib/api-client.ts";
import {
  buildContentByPathPreviewUrl,
  buildContentByPathUrl,
} from "./file-utils.ts";

const Placeholder = styled.div`
  width: 100%;
  padding-top: 56.25%; /* подложка под изображение, чтобы не прыгал layout */
  background-color: #2d2d2d;
  position: relative;
`;

const PlotWrapper = styled.div`
  .modebar-container,
  .modebar .modebar-group {
    background: rgba(0, 0, 0, 0) !important;
  }
`;

const SelectableContainer = styled.div`
  position: relative;
`;

const SelectorButton = styled.button<{ $selected: boolean; $isGraph: boolean }>`
  position: absolute;
  top: ${({ $isGraph }) => ($isGraph ? "40px" : "8px")};
  right: 8px;
  width: 24px;
  height: 24px;
  z-index: 5;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  background-color: ${({ $selected }) =>
    $selected ? "#1976d2" : "transparent"};
  border: ${({ $selected }) =>
    $selected ? "1px solid #1976d2" : "1px solid #fff"};
  color: #fff;
  box-shadow: 0 0 0 2px rgba(0, 0, 0, 0.2);
  @media print {
    display: none;
  }

  &:hover {
    transform: scale(1.05);
  }
`;

interface GraphProps {
  id: string;
  alt?: string;
  path: string;
}

const Graph: React.FC<GraphProps> = ({ id, alt, path }) => {
  const [fig, setFig] = useState<any>(null);
  const [error, setError] = useState<boolean>(false);

  useEffect(() => {
    let cancelled = false;
    const loadFigure = async () => {
      try {
        const raw = await apiClient.getTextWithRedirectInstruction(
          buildContentByPathPreviewUrl(path),
          {
            attachAuth: true,
            credentials: "omit",
            showError: false,
          },
        );
        const parsed = JSON.parse(raw);
        if (!cancelled) {
          setFig(parsed);
          setError(false);
        }
      } catch {
        if (!cancelled) {
          setError(true);
        }
      }
    };
    setFig(null);
    setError(false);
    void loadFigure();
    return () => {
      cancelled = true;
    };
  }, [path]);

  const isDark = useDarkMode();
  const { isSelected, toggle } = useSelectedAttachments();
  const selected = isSelected(id);
  const layout = useMemo(() => {
    if (!fig) return null;
    if (isDark) {
      return {
        ...fig.layout,
        template: "plotly_dark",
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        font: { color: "#fff" },
        xaxis: {
          ...fig.layout?.xaxis,
          gridcolor: "rgba(255,255,255,0.2)",
          zerolinecolor: "rgba(255,255,255,0.2)",
        },
        yaxis: {
          ...fig.layout?.yaxis,
          gridcolor: "rgba(255,255,255,0.2)",
          zerolinecolor: "rgba(255,255,255,0.2)",
        },
      };
    }
    return {
      ...fig.layout,
      template: "plotly_white",
      paper_bgcolor: "rgba(255,255,255,0)",
      plot_bgcolor: "rgba(255,255,255,0)",
      font: { color: "#111" },
      xaxis: {
        ...fig.layout?.xaxis,
        gridcolor: "rgba(0,0,0,0.15)",
        zerolinecolor: "rgba(0,0,0,0.15)",
      },
      yaxis: {
        ...fig.layout?.yaxis,
        gridcolor: "rgba(0,0,0,0.15)",
        zerolinecolor: "rgba(0,0,0,0.15)",
      },
    };
  }, [fig, isDark]);
  if (error) {
    return (
      <div>
        Ошибка загрузки вложения{" "}
        <a
          href={buildContentByPathUrl(path)}
          target="_blank"
          rel="noopener noreferrer"
        >
          {id}
        </a>
      </div>
    );
  }
  if (!fig) return <Placeholder />;
  return (
    <SelectableContainer>
      <SelectorButton
        aria-label="select-attachment"
        data-onboarding="response-attachment-selector"
        $isGraph={true}
        $selected={selected}
        onClick={(e) => {
          e.stopPropagation();
          toggle(id, alt);
        }}
      >
        {selected ? <Check size={24} /> : null}
      </SelectorButton>
      <PlotWrapper>
        <Plot
          data={fig.data}
          layout={layout}
          useResizeHandler
          style={{ width: "100%" }}
        />
      </PlotWrapper>
    </SelectableContainer>
  );
};

export default Graph;
