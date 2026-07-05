"use client";

import { useUpdateKB } from "@/lib/hooks/useKB";
import type { KBIconKey, KBTheme, KnowledgeBase } from "@/lib/kb/types";
import { Drawer } from "@heroui/react";
import { Check } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useState } from "react";
import { useKBToast } from "./KBToast";
import { ProbeSlider } from "./ProbeSlider";
import { ThemeSwatchPicker } from "./ThemeSwatchPicker";
import { KBBadge } from "./kb-visuals";

function SectionLabel({ children }: { children: string }) {
  return (
    <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-foreground-tertiary">
      {children}
    </p>
  );
}

export function EditKBDrawer({
  kb,
  isOpen,
  onOpenChange,
}: {
  kb: KnowledgeBase;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("kb.edit");
  const tCreate = useTranslations("kb.create");
  const tToast = useTranslations("kb.toast");
  const fieldId = useId();
  const { pushToast } = useKBToast();

  const [theme, setTheme] = useState<KBTheme>(kb.theme);
  const [icon, setIcon] = useState<KBIconKey>(kb.icon);
  const [displayName, setDisplayName] = useState(kb.displayName);
  const [description, setDescription] = useState(kb.description);
  const [probe, setProbe] = useState(() => Math.round((kb.pdfTextPageRatio ?? 0.2) * 100));

  useEffect(() => {
    if (!isOpen) return;
    setTheme(kb.theme);
    setIcon(kb.icon);
    setDisplayName(kb.displayName);
    setDescription(kb.description);
    setProbe(Math.round((kb.pdfTextPageRatio ?? 0.2) * 100));
  }, [isOpen, kb]);

  const updateKB = useUpdateKB();
  const canSubmit = displayName.trim().length > 0;

  const submit = async () => {
    if (!canSubmit) return;
    try {
      await updateKB.mutateAsync({
        kb_name: kb.kbName,
        display_name: displayName.trim(),
        description: description.trim(),
        theme,
        icon,
        pdf_text_page_ratio: probe / 100,
      });
      pushToast({ variant: "success", title: tToast("updated") });
      onOpenChange(false);
    } catch (err) {
      pushToast({
        variant: "error",
        title: tToast("error"),
        description: err instanceof Error ? err.message : tToast("errorDesc"),
      });
    }
  };

  const inputBase =
    "w-full rounded-xl border border-border bg-surface px-3.5 py-2.5 text-sm text-foreground outline-none transition-colors placeholder:text-foreground-secondary focus:border-field-border-focus focus:ring-4 focus:ring-accent/15";

  return (
    <Drawer isOpen={isOpen} onOpenChange={onOpenChange}>
      <Drawer.Backdrop className="data-[entering]:duration-300 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-200 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]">
        <Drawer.Content
          placement="right"
          className="data-[entering]:duration-300 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-200 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]"
        >
          <Drawer.Dialog className="w-full !max-w-none sm:w-1/3 sm:!max-w-[640px] data-[entering]:duration-300 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-200 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]">
            <Drawer.Header className="flex items-start justify-between gap-3 border-b border-separator">
              <div className="flex items-center gap-3">
                <KBBadge theme={theme} icon={icon} size={38} iconSize={20} radius={8} />
                <div className="flex flex-col gap-0.5">
                  <Drawer.Heading className="text-[17px] font-semibold leading-tight text-foreground">
                    {t("title")}
                  </Drawer.Heading>
                  <span className="font-mono text-xs text-foreground-tertiary">{kb.kbName}</span>
                </div>
              </div>
              <Drawer.CloseTrigger aria-label={t("cancel")} />
            </Drawer.Header>

            <Drawer.Body className="flex flex-col gap-6 p-5">
              {/* BASIC INFO */}
              <section className="flex flex-col gap-4">
                <SectionLabel>{tCreate("sectionBasic")}</SectionLabel>

                <div className="flex flex-col gap-2.5">
                  <span className="text-sm font-medium text-foreground">
                    {tCreate("themeLabel")}
                  </span>
                  <ThemeSwatchPicker
                    theme={theme}
                    icon={icon}
                    onChange={(th, ic) => {
                      setTheme(th);
                      setIcon(ic);
                    }}
                  />
                </div>

                <div className="flex flex-col gap-1.5">
                  <label
                    htmlFor={`${fieldId}-display`}
                    className="text-sm font-medium text-foreground"
                  >
                    {tCreate("displayLabel")} <span className="font-semibold text-danger">*</span>
                  </label>
                  <input
                    id={`${fieldId}-display`}
                    className={inputBase}
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder={tCreate("displayPlaceholder")}
                  />
                </div>

                <div className="flex flex-col gap-1.5">
                  <label
                    htmlFor={`${fieldId}-desc`}
                    className="text-sm font-medium text-foreground"
                  >
                    {tCreate("descLabel")}
                  </label>
                  <textarea
                    id={`${fieldId}-desc`}
                    rows={3}
                    className={`${inputBase} resize-none`}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder={tCreate("descPlaceholder")}
                  />
                </div>
              </section>

              {/* ADVANCED */}
              <section className="flex flex-col gap-3">
                <SectionLabel>{tCreate("sectionAdvanced")}</SectionLabel>
                <ProbeSlider
                  value={probe}
                  onChange={setProbe}
                  title={tCreate("probeTitle")}
                  sub={tCreate("probeSub")}
                  sliderLabel={tCreate("probeSliderLabel")}
                  explain={tCreate("probeExplain")}
                  lowLabel={tCreate("probeLow", { value: probe })}
                  highLabel={tCreate("probeHigh", { value: probe })}
                />
              </section>
            </Drawer.Body>

            <Drawer.Footer className="flex items-center gap-2.5 border-t border-separator">
              <button
                type="button"
                onClick={() => onOpenChange(false)}
                className="flex h-[46px] items-center justify-center rounded-xl border border-border bg-surface px-5 text-sm font-medium text-foreground transition-colors hover:bg-(--surface-muted)"
              >
                {t("cancel")}
              </button>
              <button
                type="button"
                disabled={!canSubmit || updateKB.isPending}
                onClick={submit}
                className="flex h-[46px] flex-1 items-center justify-center gap-2 rounded-xl bg-accent text-sm font-semibold text-accent-foreground shadow-[0_5px_14px_0_rgba(4,133,247,0.25)] transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Check className="h-[17px] w-[17px]" aria-hidden />
                {t("save")}
              </button>
            </Drawer.Footer>
          </Drawer.Dialog>
        </Drawer.Content>
      </Drawer.Backdrop>
    </Drawer>
  );
}
