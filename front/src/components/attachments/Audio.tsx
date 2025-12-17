import React from "react";

interface HTMLPageProps {
  id: string;
  data: any;
  alt?: string;
}

const Audio: React.FC<HTMLPageProps> = ({ data }) => {
  return (
    <audio
      controls={true}
      style={{ marginTop: "5px", marginBottom: "5px", display: "block" }}
    >
      <source
        src={`${window.location.protocol}//${window.location.host}/files${data.path}`}
      />
    </audio>
  );
};

export default Audio;
