"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { Check, Circle, CircleAlert, LoaderCircle, X } from "lucide-react";
import { useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import type { ResearchStatus } from "@/lib/model";

export function Button({
  variant = "primary",
  small = false,
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  small?: boolean;
}) {
  return (
    <button
      type="button"
      className={`button button-${variant} ${small ? "button-small" : ""} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
export function IconButton({
  label,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      type="button"
      className="icon-button"
      aria-label={label}
      title={label}
      {...props}
    >
      {children}
    </button>
  );
}
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const returnFocus = useRef<HTMLElement | null>(
    typeof document === "undefined"
      ? null
      : (document.activeElement as HTMLElement),
  );
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(value) => {
        if (!value) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className={`dialog-content ${wide ? "dialog-wide" : ""}`}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            const target = returnFocus.current;
            if (target?.isConnected) target.focus();
            else document.getElementById("workspace-title")?.focus();
          }}
        >
          <div className="dialog-heading">
            <div>
              <Dialog.Title>{title}</Dialog.Title>
              <Dialog.Description>{description}</Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <IconButton label="Close dialog">
                <X size={19} />
              </IconButton>
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
const labels: Record<ResearchStatus, string> = {
  "not-started": "Not prepared",
  running: "Preparing",
  ready: "Brief ready",
  partial: "Needs review",
  failed: "Retry needed",
};
export function ResearchBadge({ status }: { status: ResearchStatus }) {
  const Icon =
    status === "ready"
      ? Check
      : status === "running"
        ? LoaderCircle
        : status === "partial" || status === "failed"
          ? CircleAlert
          : Circle;
  return (
    <span className={`status-badge status-${status}`}>
      <Icon size={12} className={status === "running" ? "spin" : ""} />
      {labels[status]}
    </span>
  );
}
export function Avatar({
  name,
  large = false,
  index = 0,
}: {
  name: string;
  large?: boolean;
  index?: number;
}) {
  return (
    <span
      aria-hidden="true"
      className={`avatar avatar-${index % 4} ${large ? "avatar-large" : ""}`}
    >
      {name
        .trim()
        .split(/\s+/)
        .slice(0, 2)
        .map((n) => n[0])
        .join("")
        .toUpperCase()}
    </span>
  );
}
export function EmptyState({
  icon,
  title,
  children,
  action,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">{icon}</span>
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}
