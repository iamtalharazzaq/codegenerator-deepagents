import { createContext, useContext } from "react";

import { api } from "./api";

/** Where reports, task results and file previews come from: the server, or the mock data in design-review mode. */
export interface DataSource {
  report: (runId: string) => Promise<string | null>;
  artifact: (runId: string, name: string) => Promise<string>;
  file: (runId: string, path: string) => Promise<string>;
}

export const serverSource: DataSource = {
  report: (id) => api.report(id).then((r) => r.report),
  artifact: api.artifact,
  file: api.file,
};

export const DataContext = createContext<DataSource>(serverSource);
export const useData = () => useContext(DataContext);
