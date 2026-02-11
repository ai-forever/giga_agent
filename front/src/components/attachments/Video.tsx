import React from "react";
import { buildContentByPathUrl } from "./file-utils.ts";

interface VideoProps {
  id: string;
  path: string;
  alt?: string;
}

const Video: React.FC<VideoProps> = ({ path, alt }) => {
  return (
    <video
      controls
      preload="metadata"
      style={{
        width: "100%",
        maxHeight: "70vh",
        borderRadius: "8px",
        marginTop: "5px",
        marginBottom: "5px",
        display: "block",
      }}
      aria-label={alt ? `video-${alt}` : "video-attachment"}
    >
      <source src={buildContentByPathUrl(path)} />
    </video>
  );
};

export default Video;
