import React, { useEffect, useRef } from "react";
import DemoItemEditor from "./DemoItemEditor.tsx";
import { useDemoItems } from "../../hooks/DemoItemsProvider.tsx";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

interface DemoSettingsProps {}

const DemoSettings: React.FC<DemoSettingsProps> = () => {
  const { demoItems: items, addItem } = useDemoItems();
  const itemsRef = useRef<HTMLDivElement>(null);
  // храним предыдущую длину массива
  const prevLength = useRef(items.length);

  useEffect(() => {
    const el = itemsRef.current;
    // если новых элементов стало больше, чем было
    if (items.length > prevLength.current && el) {
      el.scrollTo({ top: el.scrollHeight + 100, behavior: "smooth" });
    }
    // обновляем сохранённую длину на текущее значение
    prevLength.current = items.length;
  }, [items.length]);
  const handleAdd = () => {
    addItem();
  };
  return (
    <div className="w-full flex lg:p-5 p-0 lg:mt-0 mt-[75px]">
      <div className="flex max-w-[900px] mx-auto h-full flex-1 bg-card backdrop-blur-xl rounded-lg shadow-2xl overflow-hidden print:overflow-visible print:shadow-none">
        <div
          ref={itemsRef}
          className="flex flex-col w-full h-full overflow-auto"
        >
          {items
            .sort((a, b) => a.sorting - b.sorting)
            .map((item, idx) => (
              <div key={item.id}>
                <DemoItemEditor item={item} itemIdx={idx} />
                <hr className="w-full border-border" />
              </div>
            ))}
        </div>
        <div className="fixed bottom-2.5 right-2.5">
          <Button variant="brand" size="icon" onClick={handleAdd}>
            <Plus />
          </Button>
        </div>
      </div>
    </div>
  );
};

export default DemoSettings;
