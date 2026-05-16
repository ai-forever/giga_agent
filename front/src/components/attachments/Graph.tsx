import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useDarkMode } from "@/hooks/use-dark-mode.tsx";
import styled from "styled-components";
import { useSelectedAttachments } from "../../hooks/SelectedAttachmentsContext.tsx";
import { Check } from "lucide-react";
// @ts-ignore
import createPlotlyComponentModule from "react-plotly.js/factory";
// @ts-ignore
import PlotlyModule from "plotly.js/dist/plotly";
import { apiClient } from "@/lib/api-client.ts";
import {
  buildContentByPathPreviewUrl,
  buildContentByPathUrl,
} from "./file-utils.ts";

const createPlotlyComponent =
  (createPlotlyComponentModule as any).default ?? createPlotlyComponentModule;
const Plotly = (PlotlyModule as any).default ?? PlotlyModule;
const Plot = createPlotlyComponent(Plotly);

const Placeholder = styled.div`
  width: 100%;
  padding-top: 56.25%; /* подложка под изображение, чтобы не прыгал layout */
  background-color: #2d2d2d;
  position: relative;
`;

const PlotOuter = styled.div<{ $height: number }>`
  position: relative;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  height: ${({ $height }) => `${$height}px`};
`;

const PlotScaled = styled.div<{ $scale: number; $width: number; $height: number }>`
  position: absolute;
  top: 0;
  left: 0;
  width: ${({ $width }) => `${$width}px`};
  height: ${({ $height }) => `${$height}px`};
  transform: scale(${({ $scale }) => $scale});
  transform-origin: top left;
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
            credentials: "same-origin",
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

  const nativeWidth = useMemo(() => {
    const w = Number(fig?.layout?.width);
    return w > 0 ? w : 700;
  }, [fig]);
  const nativeHeight = useMemo(() => {
    const h = Number(fig?.layout?.height);
    if (h > 0) return h;
    return Math.round(nativeWidth / (16 / 9));
  }, [fig, nativeWidth]);

  const outerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  useLayoutEffect(() => {
    if (!outerRef.current) return;
    const el = outerRef.current;
    const update = () => {
      const w = el.clientWidth;
      if (w > 0) setScale(Math.min(1, w / nativeWidth));
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [nativeWidth, fig]);

  const layout = useMemo(() => {
    if (!fig) return null;
    const base = {
      ...fig.layout,
      autosize: false,
      width: nativeWidth,
      height: nativeHeight,
    };
    if (isDark) {
      return {
        ...base,
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
      ...base,
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
  }, [fig, isDark, nativeWidth, nativeHeight]);
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
      <PlotOuter ref={outerRef} $height={nativeHeight * scale}>
        <PlotScaled
          $scale={scale}
          $width={nativeWidth}
          $height={nativeHeight}
        >
          <Plot
            data={fig.data}
            layout={layout}
            style={{ width: nativeWidth, height: nativeHeight }}
          />
        </PlotScaled>
      </PlotOuter>
    </SelectableContainer>
  );
};

export default Graph;
