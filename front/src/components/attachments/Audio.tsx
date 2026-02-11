import React from "react";
import { buildContentByPathUrl } from "./file-utils.ts";

interface AudioProps {
  id: string;
  path: string;
  alt?: string;
}

const Audio: React.FC<AudioProps> = ({ path }) => {
  return (
    <audio
      controls={true}
      style={{ marginTop: "5px", marginBottom: "5px", display: "block" }}
    >
      <source src={buildContentByPathUrl(path)} />
    </audio>
  );
};

export default Audio;
