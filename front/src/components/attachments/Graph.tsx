import React, { useEffect, useMemo, useState } from "react";
import { useDarkMode } from "@/hooks/use-dark-mode.tsx";
import styled from "styled-components";
import { useSelectedAttachments } from "../../hooks/SelectedAttachmentsContext.tsx";
import { Check } from "lucide-react";
// @ts-ignore
import Plot from "react-plotly.js";
import axios from "axios";

const Placeholder = styled.div`
  width: 100%;
  padding-top: 56.25%; /* подложка под изображение, чтобы не прыгал layout */
  background-color: #2d2d2d;
  position: relative;
`;

const Img = styled.img`
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
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
  z-index: 1000;
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
  data: any;
}

const Graph: React.FC<GraphProps> = ({ id, alt, data }) => {
  const [fig, setFig] = useState<any>(null);
  useEffect(() => {
    axios
      .get(
        `${window.location.protocol}//${window.location.host}/files${data.path}`,
      )
      .then((res) => {
        setFig(res.data);
      });
  }, [data.path]);

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
  if (!fig) return <Placeholder />;
  return (
    <SelectableContainer>
      <SelectorButton
        aria-label="select-attachment"
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
