import React, { ReactNode, useEffect } from "react";
import ReactDOM from "react-dom";
import styled from "styled-components";
import { CloseButton } from "./Attachments.tsx";

interface OverlayPortalProps {
  children: ReactNode;
  onClose: () => void;
  isVisible: boolean;
}

// Сам стилированный слой-overlay
const StyledOverlay = styled.div`
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.5);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
`;

// Контейнер для контента (можно донастроить под задачи)
// Например, картинка, модальное окно, всплывашка и т.п.
const ContentWrapper = styled.div`
  position: relative;
  max-width: 90%;
  max-height: 90%;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  overflow: auto;
`;

const OverlayPortal: React.FC<OverlayPortalProps> = ({
  children,
  onClose,
  isVisible,
}) => {
  // Создаём div-контейнер, в который будем рендерить портал
  const portalRootRef = React.useRef<HTMLDivElement | null>(null);

  if (!portalRootRef.current) {
    portalRootRef.current = document.createElement("div");
  }

  useEffect(() => {
    const portalDiv = portalRootRef.current!;
    document.body.appendChild(portalDiv);
    return () => {
      document.body.removeChild(portalDiv);
    };
  }, []);

  if (!isVisible) {
    return null;
  }

  // Обработчик клика по затемнённому фону
  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onClose?.();
    }
  };

  return ReactDOM.createPortal(
    <StyledOverlay onClick={handleOverlayClick}>
      <ContentWrapper>{children}</ContentWrapper>
      <CloseButton onClick={() => onClose?.()}>×</CloseButton>
    </StyledOverlay>,
    portalRootRef.current!,
  );
};

export default OverlayPortal;
