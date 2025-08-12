import React, { createContext, useContext, useEffect, useState } from "react";
import { DemoItem } from "../interfaces.ts";
import axios from "axios";

interface DemoItemsProps {
  children: any[] | any;
}

const DemoItemsContext = createContext<{
  demoItems: DemoItem[];
  addItem: () => void;
  removeItem: (id: string) => void;
  updateItems: () => void;
  updateItem: (item: DemoItem) => void;
  demoItemsLoaded: boolean;
}>({
  demoItems: [],
  addItem: () => {},
  removeItem: () => {},
  updateItems: () => {},
  updateItem: () => {},
  demoItemsLoaded: false,
});

export const DemoItemsProvider = ({ children }: DemoItemsProps) => {
  const [demoItems, setDemoItems] = useState<DemoItem[]>([]);
  const [demoItemsLoaded, setDemoItemsLoaded] = useState(false);
  const updateItems = () => {
    axios.get("/graph/tasks/").then((resp) => {
      setDemoItems(resp.data);
      setDemoItemsLoaded(true);
    });
  };

  useEffect(() => {
    updateItems();
  }, []);
  const addItem = () => {
    axios.post("/graph/tasks/").then((resp) => {
      setDemoItems([...demoItems, resp.data]);
    });
  };

  const removeItem = (id: string) => {
    axios.delete(`/graph/tasks/${id}/`).then(() => {
      setDemoItems(demoItems.filter((item) => item.id !== id));
    });
  };

  const updateItem = (item: DemoItem) => {
    axios.put(`/graph/tasks/${item.id}/`, item).then(() => {});
  };

  return (
    <DemoItemsContext.Provider
      value={{
        demoItems,
        addItem,
        removeItem,
        updateItems,
        updateItem,
        demoItemsLoaded,
      }}
    >
      {children}
    </DemoItemsContext.Provider>
  );
};

// Хук для удобного доступа
export const useDemoItems = () => useContext(DemoItemsContext);
