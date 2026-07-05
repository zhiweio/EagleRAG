"use client";

import { useCreateKB } from "@/lib/hooks/useKB";
import type { KBIconKey, KBTheme } from "@/lib/kb/types";
import { Drawer } from "@heroui/react";
import { Check, ChevronDown, Database, Hash, Lock } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { useKBToast } from "./KBToast";
import { ProbeSlider } from "./ProbeSlider";
import { ThemeSwatchPicker } from "./ThemeSwatchPicker";

const KB_NAME_RE = /^[a-z][a-z0-9_]*$/;

/** Form section label (BASIC INFO / ADVANCED SETTINGS). */
function SectionLabel({ children }: { children: string }) {
  return (
    <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-foreground-tertiary">
      {children}
    </p>
  );
}

export function CreateKBDrawer({
  isOpen,
  onOpenChange,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("kb.create");
  const tToast = useTranslations("kb.toast");
  const fieldId = useId();
  const { pushToast } = useKBToast();

  const [theme, setTheme] = useState<KBTheme>("blue");
  const [icon, setIcon] = useState<KBIconKey>("landmark");
  const [kbName, setKbName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [probe, setProbe] = useState(20);
  const [collapsed, setCollapsed] = useState(true);

  const kbNameInvalid = kbName.length > 0 && !KB_NAME_RE.test(kbName);
  const canSubmit = KB_NAME_RE.test(kbName) && displayName.trim().length > 0;

  const reset = () => {
    setTheme("blue");
    setIcon("landmark");
    setKbName("");
    setDisplayName("");
    setDescription("");
    setProbe(20);
    setCollapsed(true);
  };

  const close = () => {
    onOpenChange(false);
  };

  const createKB = useCreateKB();

  const submit = async () => {
    if (!canSubmit) return;
    try {
      await createKB.mutateAsync({
        kb_name: kbName,
        display_name: displayName.trim(),
        description: description.trim(),
        theme,
        icon,
        pdf_text_page_ratio: probe / 100,
      });
      pushToast({ variant: "success", title: tToast("created") });
      reset();
      close();
    } catch (err) {
      pushToast({
        variant: "error",
        title: tToast("error"),
        description: err instanceof Error ? err.message : tToast("errorDesc"),
      });
    }
  };

  const inputBase =
    "w-full rounded-xl border bg-surface px-3.5 py-2.5 text-sm text-foreground outline-none transition-colors placeholder:text-foreground-secondary focus:border-field-border-focus focus:ring-4 focus:ring-accent/15";

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
                <span className="flex h-[38px] w-[38px] shrink-0 items-center justify-center rounded-lg bg-accent-soft">
                  <Database className="h-5 w-5 text-accent-soft-foreground" aria-hidden />
                </span>
                <div className="flex flex-col gap-0.5">
                  <Drawer.Heading className="text-[17px] font-semibold leading-tight text-foreground">
                    {t("title")}
                  </Drawer.Heading>
                  <span className="text-xs text-foreground-tertiary">{t("subtitle")}</span>
                </div>
              </div>
              <Drawer.CloseTrigger aria-label={t("cancel")} />
            </Drawer.Header>

            <Drawer.Body className="flex flex-col gap-6 p-5">
              <p className="text-sm leading-relaxed text-foreground-secondary">{t("desc")}</p>

              {/* BASIC INFO */}
              <section className="flex flex-col gap-4">
                <SectionLabel>{t("sectionBasic")}</SectionLabel>

                {/* Theme + icon picker */}
                <div className="flex flex-col gap-2.5">
                  <span className="text-sm font-medium text-foreground">{t("themeLabel")}</span>
                  <ThemeSwatchPicker
                    theme={theme}
                    icon={icon}
                    onChange={(th, ic) => {
                      setTheme(th);
                      setIcon(ic);
                    }}
                  />
                </div>

                {/* kb_name */}
                <div className="flex flex-col gap-2">
                  <label
                    htmlFor={`${fieldId}-kbname`}
                    className="text-sm font-medium text-foreground"
                  >
                    {t("kbNameLabel")} <span className="font-semibold text-danger">*</span>
                  </label>
                  <div
                    className={`flex h-11 items-center gap-2 rounded-xl border bg-surface px-3.5 transition-colors focus-within:ring-4 focus-within:ring-accent/15 ${
                      kbNameInvalid
                        ? "border-danger focus-within:border-danger focus-within:ring-danger/15"
                        : "border-field-border-focus"
                    }`}
                  >
                    <Hash className="h-4 w-4 shrink-0 text-foreground-secondary" aria-hidden />
                    <input
                      id={`${fieldId}-kbname`}
                      value={kbName}
                      onChange={(e) => setKbName(e.target.value.trim())}
                      placeholder={t("kbNamePlaceholder")}
                      aria-invalid={kbNameInvalid}
                      className="w-full bg-transparent font-mono text-sm text-foreground outline-none placeholder:text-foreground-secondary"
                    />
                  </div>
                  {kbNameInvalid ? (
                    <p className="text-xs text-danger">{t("kbNameError")}</p>
                  ) : (
                    <div className="flex items-start gap-1.5">
                      <Lock
                        className="mt-0.5 h-[13px] w-[13px] shrink-0 text-foreground-tertiary"
                        aria-hidden
                      />
                      <p className="text-[11px] leading-[1.45] text-foreground-tertiary">
                        {t("kbNameHint")}
                      </p>
                    </div>
                  )}
                </div>

                {/* display name */}
                <div className="flex flex-col gap-1.5">
                  <label
                    htmlFor={`${fieldId}-display`}
                    className="text-sm font-medium text-foreground"
                  >
                    {t("displayLabel")} <span className="text-danger">*</span>
                  </label>
                  <input
                    id={`${fieldId}-display`}
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder={t("displayPlaceholder")}
                    className={`${inputBase} border-border`}
                  />
                </div>

                {/* description */}
                <div className="flex flex-col gap-1.5">
                  <label
                    htmlFor={`${fieldId}-desc`}
                    className="flex items-center gap-2 text-sm font-medium text-foreground"
                  >
                    {t("descLabel")}
                    <span className="rounded-full bg-background-secondary px-2 py-0.5 text-[10px] font-normal text-foreground-tertiary">
                      {t("descOptional")}
                    </span>
                  </label>
                  <textarea
                    id={`${fieldId}-desc`}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder={t("descPlaceholder")}
                    rows={3}
                    className={`${inputBase} resize-none border-border`}
                  />
                </div>
              </section>

              {/* ADVANCED SETTINGS */}
              <section className="flex flex-col gap-3">
                <SectionLabel>{t("sectionAdvanced")}</SectionLabel>

                {/* PDF probe */}
                <ProbeSlider
                  value={probe}
                  onChange={setProbe}
                  title={t("probeTitle")}
                  sub={t("probeSub")}
                  sliderLabel={t("probeSliderLabel")}
                  explain={t("probeExplain")}
                  lowLabel={t("probeLow", { value: probe })}
                  highLabel={t("probeHigh", { value: probe })}
                />

                {/* Collections binding (accordion) */}
                <div className="overflow-hidden rounded-xl border border-border">
                  <button
                    type="button"
                    onClick={() => setCollapsed((v) => !v)}
                    aria-expanded={!collapsed}
                    className="flex w-full items-center gap-[11px] bg-surface px-3.5 py-[13px] text-left transition-colors hover:bg-(--surface-muted)"
                  >
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-violet-100">
                      <Database className="h-[17px] w-[17px] text-violet-600" aria-hidden />
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col gap-px">
                      <span className="text-[13px] font-semibold text-foreground">
                        {t("collectionsTitle")}
                      </span>
                      <span className="font-mono text-[11px] text-foreground-tertiary">
                        {t("collectionsSub")}
                      </span>
                    </span>
                    <ChevronDown
                      className={`h-4 w-4 shrink-0 text-foreground-tertiary transition-transform ${collapsed ? "" : "rotate-180"}`}
                      aria-hidden
                    />
                  </button>
                  {collapsed ? null : (
                    <div className="border-t border-separator bg-(--surface-muted) px-3.5 py-3">
                      <p className="text-xs leading-relaxed text-foreground-secondary">
                        {t("collectionsHint")}
                      </p>
                    </div>
                  )}
                </div>
              </section>
            </Drawer.Body>

            <Drawer.Footer className="flex items-center gap-2.5 border-t border-separator">
              <button
                type="button"
                onClick={close}
                className="flex h-[46px] items-center justify-center rounded-xl border border-border bg-surface px-5 text-sm font-medium text-foreground transition-colors hover:bg-(--surface-muted)"
              >
                {t("cancel")}
              </button>
              <button
                type="button"
                disabled={!canSubmit || createKB.isPending}
                onClick={submit}
                className="flex h-[46px] flex-1 items-center justify-center gap-2 rounded-xl bg-accent text-sm font-semibold text-accent-foreground shadow-[0_5px_14px_0_rgba(4,133,247,0.25)] transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Check className="h-[17px] w-[17px]" aria-hidden />
                {createKB.isPending ? t("pending") : t("submit")}
              </button>
            </Drawer.Footer>
          </Drawer.Dialog>
        </Drawer.Content>
      </Drawer.Backdrop>
    </Drawer>
  );
}
