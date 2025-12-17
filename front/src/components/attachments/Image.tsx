import React from "react";
import styled from "styled-components";
import { useSelectedAttachments } from "../../hooks/SelectedAttachmentsContext.tsx";
import { Check } from "lucide-react";

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

interface ImageProps {
  id: string;
  data: any;
  alt?: string;
}

const Image: React.FC<ImageProps> = ({ id, data, alt }) => {
  const { isSelected, toggle } = useSelectedAttachments();
  const selected = isSelected(id);

  return (
    <SelectableContainer>
      <SelectorButton
        aria-label="select-attachment"
        $isGraph={false}
        $selected={selected}
        onClick={(e) => {
          e.stopPropagation();
          toggle(id, alt);
        }}
      >
        {selected ? <Check size={24} /> : null}
      </SelectorButton>
      <div style={{ display: "flex" }}>
        <img
          src={`${window.location.protocol}//${window.location.host}/files${data.path}`}
          alt={`attachment-${alt}`}
          style={{
            maxWidth: "100%",
            borderRadius: "4px",
            margin: "auto",
          }}
        />
      </div>
    </SelectableContainer>
  );
};

export default Image;
