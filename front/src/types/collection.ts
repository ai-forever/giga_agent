export type Collection = {
  name: string;
  uuid: string;
  can_edit: boolean;
  metadata: {
    description?: string;
    [key: string]: any;
  };
};

export type CollectionCreate = {
  name: string;
  metadata: Record<string, any>;
};
