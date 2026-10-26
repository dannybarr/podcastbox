"use client";

import { cloneElement, isValidElement, type ReactElement, type ReactNode } from "react";

type AnyProps = Record<string, unknown>;

function cx(...parts: Array<string | false | undefined>) {
  return parts.filter(Boolean).join(" ");
}

const typeClass: Record<string, string> = {
  overline: "pb-overline",
  "headline-1": "pb-h1",
  "headline-2": "pb-h2",
  "headline-3": "pb-h3",
  "headline-4": "pb-h4",
  "subtitle-2": "pb-sub-2",
  "subtitle-3": "pb-sub-3",
  "body-2": "pb-body",
  "body-3": "pb-body-sm",
  label: "pb-label",
  "label-small": "pb-label-sm",
};

export function Typography({
  variant = "body-2",
  tag = "p",
  colorScheme,
  className,
  children,
  ...rest
}: {
  variant?: string;
  tag?: keyof HTMLElementTagNameMap;
  colorScheme?: string;
  className?: string;
  children?: ReactNode;
} & AnyProps) {
  const Tag = tag as "p";
  return (
    <Tag className={cx(typeClass[variant] || "pb-body", colorScheme === "subtle" && "pb-subtle", className)} {...rest}>
      {children}
    </Tag>
  );
}

export function Button({
  colorScheme,
  destructive,
  element,
  iconButton,
  buttonSize,
  className,
  children,
  type = "button",
  ...rest
}: {
  colorScheme?: "primary" | "secondary" | "tertiary";
  destructive?: boolean;
  element?: ReactElement;
  iconButton?: boolean;
  buttonSize?: string;
  className?: string;
  children?: ReactNode;
  type?: "button" | "submit" | "reset";
} & AnyProps) {
  const classes = cx(
    "pb-btn",
    colorScheme === "secondary" && "pb-btn-secondary",
    colorScheme === "tertiary" && "pb-btn-tertiary",
    destructive && "pb-btn-danger",
    iconButton && "pb-btn-icon",
    buttonSize === "large" && "pb-btn-large",
    className,
  );
  if (isValidElement(element)) {
    const current = element.props as { className?: string };
    return cloneElement(element, { className: cx(classes, current.className) } as AnyProps, children);
  }
  return (
    <button type={type} className={classes} {...rest}>
      {children}
    </button>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx("pb-input", props.className)} />;
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx("pb-input", "pb-textarea", props.className)} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx("pb-input", props.className)} />;
}

export function Checkbox(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input type="checkbox" {...props} className={cx("pb-check", props.className)} />;
}

export function Radio(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input type="radio" {...props} className={cx("pb-check", props.className)} />;
}

export function Label({ className, children, ...rest }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label className={cx("pb-label", className)} {...rest}>
      {children}
    </label>
  );
}

export function InputContainer({ children }: { children?: ReactNode }) {
  return <div className="pb-field">{children}</div>;
}

export function InputMessage({ id, children }: { id?: string; children?: ReactNode }) {
  return (
    <p id={id} className="pb-hint">
      {children}
    </p>
  );
}

export function Dialog({
  children,
  className,
  ...rest
}: React.DialogHTMLAttributes<HTMLDialogElement>) {
  return (
    <dialog className={cx("pb-dialog", className)} {...rest}>
      {children}
    </dialog>
  );
}

export function DialogHeader({ children, ...rest }: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2 className="pb-h4" {...rest}>
      {children}
    </h2>
  );
}

export function DialogContent({ children }: { children?: ReactNode }) {
  return <div className="pb-dialog-body">{children}</div>;
}

export function Badge({ children }: { badgeType?: string; children?: ReactNode }) {
  return <span className="pb-badge">{children}</span>;
}

export function Flag({ messageType = "information", children }: { messageType?: string; children?: ReactNode }) {
  return <div className={cx("pb-flag", `pb-flag-${messageType}`)}>{children}</div>;
}

export function FlagContent({ children }: { children?: ReactNode }) {
  return <div className="pb-flag-body">{children}</div>;
}

export function Banner({ messageType = "information", children }: { messageType?: string; children?: ReactNode }) {
  return (
    <div className={cx("pb-banner", `pb-banner-${messageType}`)} role="alert">
      {children}
    </div>
  );
}

export function BannerContent({ children }: { children?: ReactNode }) {
  return <div>{children}</div>;
}

export function Avatar({ children }: { children?: ReactNode } & AnyProps) {
  return <span className="pb-avatar">{children}</span>;
}

export function Link({
  element,
  noUnderline,
  className,
  children,
  ...rest
}: {
  element?: ReactElement;
  noUnderline?: boolean;
  className?: string;
  children?: ReactNode;
} & AnyProps) {
  const classes = cx(!noUnderline && "pb-link", className);
  if (isValidElement(element)) {
    const current = element.props as { className?: string };
    return cloneElement(element, { className: cx(classes, current.className), ...rest } as AnyProps, children);
  }
  return (
    <a className={classes} {...rest}>
      {children}
    </a>
  );
}

export function Utility({
  tag = "div",
  vFlex,
  vAlignItems,
  vJustifyContent,
  vGap,
  vPaddingHorizontal,
  vPaddingVertical,
  vFlexWrap,
  className,
  style,
  children,
  ...rest
}: {
  tag?: keyof HTMLElementTagNameMap;
  vFlex?: boolean;
  vAlignItems?: string;
  vJustifyContent?: string;
  vGap?: number;
  vPaddingHorizontal?: number;
  vPaddingVertical?: number;
  vFlexWrap?: boolean;
  className?: string;
  style?: React.CSSProperties;
  children?: ReactNode;
} & AnyProps) {
  const Tag = tag as "div";
  const justify = vJustifyContent === "between" ? "space-between" : vJustifyContent === "center" ? "center" : vJustifyContent;
  return (
    <Tag
      className={className}
      style={{
        display: vFlex ? "flex" : undefined,
        alignItems: vAlignItems,
        justifyContent: justify,
        gap: vGap,
        paddingInline: vPaddingHorizontal,
        paddingBlock: vPaddingVertical,
        flexWrap: vFlexWrap ? "wrap" : undefined,
        ...style,
      }}
      {...rest}
    >
      {children}
    </Tag>
  );
}
