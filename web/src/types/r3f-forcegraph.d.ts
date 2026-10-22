// r3f-forcegraph ships no type declarations; declare the module so the default import type-checks.
// Its imperative methods (tickFrame, etc.) are reached through a ref typed as the component instance.
declare module "r3f-forcegraph";
