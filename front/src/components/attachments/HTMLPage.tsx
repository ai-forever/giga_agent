import React, { useEffect, useState, useRef } from "react";
import styled from "styled-components";

// Обертка iframe: управляет шириной и макс. шириной
const IframeWrapper = styled.div<{ fullScreen: boolean }>`
  position: relative;
  border-radius: 8px;
  width: ${({ fullScreen }) => (fullScreen ? "70vw" : "100%")};
  max-width: ${({ fullScreen }) => (fullScreen ? "auto" : "700px")};
  aspect-ratio: 16 / 9;
  margin: auto;
  background-color: #1f1f1f;
`;

// Сам iframe: фиксированный базовый размер, скейлится
const StyledIframe = styled.iframe<{ scale: number }>`
  position: absolute;
  top: 0;
  left: 0;
  border-radius: 8px;
  width: ${({ scale }) => `${100 / scale}%`};
  height: ${({ scale }) => `${100 / scale}%`};
  transform-origin: top left;
  border: none;
  transform: scale(${({ scale }) => scale});
`;

interface HTMLPageProps {
  id: string;
  data: any;
  alt?: string;
  fullScreen?: boolean;
}

const HTMLPage: React.FC<HTMLPageProps> = ({
  data,
  alt,
  fullScreen = false,
}) => {
  const [scale, setScale] = useState<number>(fullScreen ? 0.8 : 0.5);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const recalc = () => {
    if (!wrapperRef.current) return;
    // ширина контейнера в px
    const containerWidth = wrapperRef.current.clientWidth;
    // базовая ширина для 100% = 700px
    const baseWidth = 700;
    let newScale = containerWidth / baseWidth / 2;
    // wrapperRef.current.style = {};
    // не увеличиваем более 1
    newScale = Math.min(newScale, fullScreen ? 0.8 : 0.5);
    setScale(newScale);
  };

  useEffect(() => {
    recalc();
  }, [wrapperRef.current]);

  // Пересчет масштаба при изменении размера контейнера
  useEffect(() => {
    recalc();
    window.addEventListener("resize", recalc);
    return () => window.removeEventListener("resize", recalc);
  }, [fullScreen]);

  return (
    <IframeWrapper ref={wrapperRef} fullScreen={fullScreen}>
      <StyledIframe
        title={alt || `iframe-${data.path}`}
        src={`${window.location.protocol}//${window.location.host}/files${data.path}`}
        sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-modals allow-forms"
        scale={scale}
      />
    </IframeWrapper>
  );
};

export default HTMLPage;
