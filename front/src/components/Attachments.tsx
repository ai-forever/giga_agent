import styled from "styled-components";

export const AttachmentsContainer = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
`;

export const ImagePreview = styled.img`
  width: 40px;
  height: 40px;
  object-fit: cover;
  border-radius: 4px;
`;

export const AttachmentBubble = styled.div`
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background-color: var(--color-secondary);
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  &:hover {
    background-color: var(--color-secondary);
  }
`;

export const RemoveButton = styled.button`
  background: none;
  border: none;
  color: #ff6b6b;
  cursor: pointer;
  padding: 0;
  font-size: 16px;
  line-height: 1;

  &:hover {
    color: #ff8787;
  }
`;

export const Overlay = styled.div`
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.8);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
`;

export const EnlargedImage = styled.img`
  max-width: 90%;
  max-height: 90vh;
  object-fit: contain;
`;

export const CircularProgress = styled.div<{ progress: number }>`
  width: 40px;
  height: 40px;
  background: conic-gradient(
    #4caf50 ${({ progress }) => progress * 3.6}deg,
    #555 0deg
  );
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: white;
`;

export const ProgressOverlay = styled.div`
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
`;

export const CloseButton = styled.button`
  position: absolute;
  top: 20px;
  right: 20px;
  background: none;
  border: none;
  color: white;
  font-size: 24px;
  cursor: pointer;
  padding: 8px;
  border-radius: 4px;
  background-color: rgba(255, 255, 255, 0.1);

  &:hover {
    background-color: rgba(255, 255, 255, 0.2);
  }
`;
