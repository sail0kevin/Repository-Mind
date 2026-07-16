import defaultTool, { helper as renamed } from "./helpers";
export { renamed };

export interface Worker extends BaseWorker {
  run(value: string): void;
}

export class Service extends Parent implements Worker {
  run(value: string) {
    renamed(value);
    this.finish();
    defaultTool.send(value);
  }

  finish() {}
}

export const launch = (value: string) => renamed(value);

export default function main() {
  return launch("ok");
}
