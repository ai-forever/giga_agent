import React, { useMemo, useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";

export type Option = {
  value: string;
  label: string;
  disabled?: boolean;
};

type SearchableSelectProps = {
  options: Option[];
  value?: string;
  onValueChange: (value: string) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  disabled?: boolean;
  className?: string;
};

type SearchableMultiSelectProps = {
  options: Option[];
  values: string[];
  onValuesChange: (values: string[]) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  disabled?: boolean;
  className?: string;
  maxVisibleLabels?: number;
};

function SearchableSelect({
  options,
  value,
  onValueChange,
  placeholder = "Выберите значение",
  searchPlaceholder = "Поиск...",
  emptyText = "Ничего не найдено",
  disabled,
  className,
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false);
  const selectedOption = options.find((option) => option.value === value);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className={cn(
            "w-full justify-between font-normal",
            !selectedOption && "text-muted-foreground",
            className,
          )}
        >
          <span className="truncate">
            {selectedOption?.label ?? placeholder}
          </span>
          <ChevronsUpDown className="ml-2 size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[var(--radix-popover-trigger-width)] p-0"
        align="start"
      >
        <Command>
          <CommandInput placeholder={searchPlaceholder} />
          <CommandList>
            <CommandEmpty>{emptyText}</CommandEmpty>
            {options.map((option) => (
              <CommandItem
                key={option.value}
                value={option.label}
                disabled={option.disabled}
                onSelect={() => {
                  onValueChange(option.value);
                  setOpen(false);
                }}
              >
                <Check
                  className={cn(
                    "mr-2 size-4",
                    option.value === value ? "opacity-100" : "opacity-0",
                  )}
                />
                <span className="truncate">{option.label}</span>
              </CommandItem>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

function SearchableMultiSelect({
  options,
  values,
  onValuesChange,
  placeholder = "Выберите значения",
  searchPlaceholder = "Поиск...",
  emptyText = "Ничего не найдено",
  disabled,
  className,
  maxVisibleLabels = 2,
}: SearchableMultiSelectProps) {
  const [open, setOpen] = useState(false);

  const selectedOptions = useMemo(() => {
    const selectedSet = new Set(values);
    return options.filter((option) => selectedSet.has(option.value));
  }, [options, values]);

  const triggerLabel = useMemo(() => {
    if (selectedOptions.length === 0) {
      return placeholder;
    }

    if (selectedOptions.length <= maxVisibleLabels) {
      return selectedOptions.map((option) => option.label).join(", ");
    }

    return `Выбрано: ${selectedOptions.length}`;
  }, [maxVisibleLabels, placeholder, selectedOptions]);
  const visibleSelectedOptions = selectedOptions.slice(0, maxVisibleLabels);
  const hiddenSelectedCount = Math.max(
    selectedOptions.length - maxVisibleLabels,
    0,
  );

  const selectedSet = useMemo(() => new Set(values), [values]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className={cn(
            "w-full justify-between font-normal whitespace-normal min-h-9 h-auto py-1",
            selectedOptions.length === 0 && "text-muted-foreground",
            className,
          )}
        >
          {selectedOptions.length === 0 ? (
            <span className="truncate">{triggerLabel}</span>
          ) : (
            <span className="flex min-w-0 flex-1 flex-wrap items-center gap-1">
              {visibleSelectedOptions.map((option) => (
                <Badge
                  key={option.value}
                  variant="default"
                  className="max-w-full truncate"
                >
                  {option.label}
                </Badge>
              ))}
              {hiddenSelectedCount > 0 && (
                <Badge variant="secondary">{`+${hiddenSelectedCount}`}</Badge>
              )}
            </span>
          )}
          <ChevronsUpDown className="ml-2 size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[var(--radix-popover-trigger-width)] p-0"
        align="start"
      >
        <Command>
          <CommandInput placeholder={searchPlaceholder} />
          <CommandList>
            <CommandEmpty>{emptyText}</CommandEmpty>
            {options.map((option) => {
              const isSelected = selectedSet.has(option.value);
              return (
                <CommandItem
                  key={option.value}
                  value={option.label}
                  disabled={option.disabled}
                  onSelect={() => {
                    if (isSelected) {
                      onValuesChange(
                        values.filter((item) => item !== option.value),
                      );
                    } else {
                      onValuesChange([...values, option.value]);
                    }
                  }}
                >
                  <Check
                    className={cn(
                      "mr-2 size-4",
                      isSelected ? "opacity-100" : "opacity-0",
                    )}
                  />
                  <span className="truncate">{option.label}</span>
                </CommandItem>
              );
            })}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

export { SearchableSelect, SearchableMultiSelect };
