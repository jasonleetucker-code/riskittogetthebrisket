/**
 * Design-system barrel — Redesign R0 foundation.
 *
 * Import primitives from here:
 *   import { Panel, DataTable, Movement } from "@/components/ds";
 *
 * This library supersedes the legacy components/ui/* primitives (which
 * stay untouched until R1+ migrates their importers) and the three
 * container systems (.card / terminal Panel / league Card). Living
 * reference: /design. Rules + rationale: docs/DESIGN-SYSTEM.md.
 */
export { Icon, ICON_NAMES } from "./Icon";
export { Button } from "./Button";
export { Field, Input } from "./Input";
export { Select } from "./Select";
export { SegmentedControl } from "./SegmentedControl";
export { Panel } from "./Panel";
export { CollapsiblePanel } from "./CollapsiblePanel";
export { PageHeader } from "./PageHeader";
export { ValueBasisNote } from "./ValueBasisNote";
export { StatTile } from "./StatTile";
export { DataTable, sortRows } from "./DataTable";
export { Tabs, tabId, tabPanelId } from "./Tabs";
export {
  Badge,
  StatusIndicator,
  Movement,
  Confidence,
  confidenceBucket,
} from "./Badge";
export { Tooltip } from "./Tooltip";
export { InfoTip, HelpModal } from "./Help";
export { PlayerNameButton } from "./PlayerNameButton";
export { Modal, Drawer } from "./Dialog";
export {
  Skeleton,
  SkeletonText,
  SkeletonRow,
  SkeletonTable,
  SkeletonStat,
} from "./Skeleton";
export { EmptyState } from "./EmptyState";
export { Banner } from "./Banner";
export { Sparkline, Meter } from "./Sparkline";
export {
  REQUIRED_TOKENS,
  LIGHT_THEME_REQUIRED,
  CHART_SERIES_TOKENS,
} from "./token-contract";
