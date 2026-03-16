import React, { Suspense } from "react";
import Text from "./Text.tsx";
import HTMLPage from "./HTMLPage.tsx";
import Image from "./Image.tsx";
import Audio from "./Audio.tsx";
import Video from "./Video.tsx";
import {
  AttachmentFileType,
  buildContentByPathUrl,
  inferAttachmentTypeFromPath,
  resolveAttachmentPath,
} from "./file-utils.ts";

const Graph = React.lazy(() => import("./Graph.tsx"));

interface MessageAttachmentProps {
  path: string;
  fileType?: AttachmentFileType;
  fullScreen?: boolean;
  alt?: string;
}

const MessageAttachment: React.FC<MessageAttachmentProps> = ({
  path,
  fileType,
  alt,
  fullScreen,
}) => {
  const effectivePath = resolveAttachmentPath(path);
  const effectiveType = fileType ?? inferAttachmentTypeFromPath(effectivePath);

  if (!effectivePath) {
    return <div>Ошибка загрузки вложения {alt || ""}</div>;
  }

  if (effectiveType === "plotly_graph") {
    return (
      <Suspense
        fallback={
          <div
            style={{
              width: "100%",
              paddingTop: "56.25%",
              backgroundColor: "#2d2d2d",
            }}
          />
        }
      >
        <Graph path={effectivePath} alt={alt} id={effectivePath} />
      </Suspense>
    );
  } else if (effectiveType === "text") {
    return <Text path={effectivePath} alt={alt} id={effectivePath} />;
  } else if (effectiveType === "html") {
    return (
      <HTMLPage
        path={effectivePath}
        alt={alt}
        id={effectivePath}
        fullScreen={fullScreen ? fullScreen : false}
      />
    );
  } else if (effectiveType === "image") {
    return <Image path={effectivePath} alt={alt} id={effectivePath} />;
  } else if (effectiveType === "audio") {
    return <Audio path={effectivePath} alt={alt} id={effectivePath} />;
  } else if (effectiveType === "video") {
    return <Video path={effectivePath} alt={alt} id={effectivePath} />;
  } else {
    const name = effectivePath.split("/").at(-1) || effectivePath;
    return (
      <div>
        Ошибка загрузки вложения {alt || ""}
        {" - "}
        <a
          href={buildContentByPathUrl(effectivePath)}
          target="_blank"
          rel="noopener noreferrer"
        >
          {name}
        </a>
      </div>
    );
  }
};

export default React.memo(
  MessageAttachment,
  (prev, next) =>
    prev.path === next.path &&
    prev.alt === next.alt &&
    prev.fileType === next.fileType &&
    prev.fullScreen === next.fullScreen,
);
