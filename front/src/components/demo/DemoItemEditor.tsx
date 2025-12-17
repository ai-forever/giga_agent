import React, { useEffect, useState } from "react";
import { DemoItem } from "../../interfaces.ts";
import { useFileUpload } from "../../hooks/useFileUploads.ts";
import { Check, CopyX, Paperclip, Play, Save } from "lucide-react";
import {
  AttachmentBubble,
  AttachmentsContainer,
  CircularProgress,
  EnlargedImage,
  ImagePreview,
  ProgressOverlay,
  RemoveButton,
} from "../Attachments.tsx";
import OverlayPortal from "../OverlayPortal.tsx";
import { useNavigate } from "react-router-dom";
import { useDemoItems } from "../../hooks/DemoItemsProvider.tsx";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";

interface DemoItemEditorProps {
  item: DemoItem;
  itemIdx: number;
}

const DemoItemEditor: React.FC<DemoItemEditorProps> = ({ item, itemIdx }) => {
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const [enlargedImage, setEnlargedImage] = useState<string | null>(null);
  const {
    uploadFiles,
    resetUploads,
    setExistingFiles,
    items,
    removeItem: removeAttachmentItem,
    getAllFileData,
  } = useFileUpload();
  const [steps, setSteps] = useState(10);
  const [active, setActive] = useState(false);
  const [message, setMessage] = useState("");
  const navigate = useNavigate();
  const { removeItem, updateItem } = useDemoItems();

  useEffect(() => {
    setMessage(item.json_data.message ? item.json_data.message : "");
    setExistingFiles(
      item.json_data.attachments ? item.json_data.attachments : [],
    );
    setSteps(item.steps);
    setActive(item.active);
  }, [item.json_data, item.steps, item.active, setExistingFiles]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      uploadFiles(Array.from(e.target.files));
      e.target.value = "";
    }
  };

  const handleDelete = () => {
    // eslint-disable-next-line no-restricted-globals
    if (confirm("Подтверждаете удаление?")) {
      removeItem(item.id);
    }
  };

  const openLink = (url: string) => {
    const win = window.open(url, "_blank");
    win?.focus();
  };

  const handlePlay = () => {
    navigate(`/demo/${itemIdx}`);
  };

  const handleSave = () => {
    const allFiles = getAllFileData();
    const data: DemoItem = {
      id: item.id,
      json_data: {
        message: message,
        attachments: allFiles,
      },
      steps: steps,
      sorting: item.sorting,
      active: active,
    };
    updateItem(data);
  };

  return (
    <div className="p-5">
      <div className="flex flex-row items-center gap-2">
        <div className="flex items-center mr-1">
          <Switch
            checked={active}
            onCheckedChange={(v) => setActive(v)}
            aria-label="Активно"
          />
        </div>

        <div className="flex flex-1 items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="icon"
            title="Добавить вложения"
            onClick={() => fileInputRef.current?.click()}
          >
            <Paperclip />
          </Button>

          <Textarea
            placeholder="Спросите что-нибудь…"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            className="resize-none max-h-[200px] min-h-[60px] flex-1 overflow-y-auto"
          />

          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            multiple
            className="hidden"
          />
        </div>

        <div className="flex items-center">
          <Input
            type="number"
            value={Number.isFinite(steps) ? steps : 0}
            onChange={(e) => setSteps(e.target.valueAsNumber)}
            className="w-24"
          />
        </div>

        <div className="flex flex-col items-center gap-2">
          <Button
            variant="destructive"
            size="icon"
            title="Удалить"
            onClick={handleDelete}
          >
            <CopyX />
          </Button>
          <Button
            variant="brand"
            size="icon"
            title="Сохранить"
            onClick={handleSave}
          >
            <Save />
          </Button>
        </div>

        <div className="flex items-center">
          <Button
            variant="outline"
            size="icon"
            title="Запустить"
            onClick={handlePlay}
          >
            <Play />
          </Button>
        </div>

        <OverlayPortal
          isVisible={!!enlargedImage}
          onClose={() => setEnlargedImage(null)}
        >
          <EnlargedImage src={enlargedImage ?? ""} />
        </OverlayPortal>
      </div>

      <div className="flex w-full mt-3">
        {items.length > 0 && (
          <AttachmentsContainer>
            {items.map((it, idx) => (
              <AttachmentBubble
                key={idx}
                onClick={() => {
                  if (it.kind === "existing") {
                    const f = it.data!;
                    if (f.file_type === "image")
                      setEnlargedImage("/files/" + f.path);
                    else openLink("/files/" + f.path);
                  } else if (it.previewUrl) {
                    setEnlargedImage(it.previewUrl);
                  }
                }}
              >
                {it.kind === "existing" ? (
                  it.data?.file_type === "image" ? (
                    <ImagePreview src={"/files/" + it.data.path} />
                  ) : (
                    <span>
                      {it.name ?? it.data?.path.replace(/^files\//, "")}
                    </span>
                  )
                ) : it.previewUrl ? (
                  <ImagePreview src={it.previewUrl} />
                ) : (
                  <span>{it.name}</span>
                )}

                {it.progress < 100 && (
                  <ProgressOverlay>
                    <CircularProgress progress={it.progress}>
                      {it.progress}%
                    </CircularProgress>
                  </ProgressOverlay>
                )}

                <RemoveButton
                  onClick={(e) => {
                    e.stopPropagation();
                    removeAttachmentItem(idx);
                  }}
                >
                  ×
                </RemoveButton>
              </AttachmentBubble>
            ))}
          </AttachmentsContainer>
        )}
      </div>
    </div>
  );
};

export default React.memo(
  DemoItemEditor,
  (prev, next) => prev.item === next.item && prev.itemIdx === next.itemIdx,
);
