export const SPECIALISTS: ReadonlyArray<readonly [string, string]> = [
  ["business_analyst", "Business Analyst"],
  ["product_manager", "Product Manager"],
  ["solution_architect", "Solution Architect"],
  ["code_analyst", "Code Analyst"],
  ["database_engineer", "Database Engineer"],
  ["backend_developer", "Backend Developer"],
  ["frontend_developer", "Frontend Developer"],
  ["ui_ux_designer", "UI/UX Designer"],
  ["qa_engineer", "QA Engineer"],
  ["devops_engineer", "DevOps Engineer"],
];

const LABELS: Record<string, string> = { project_manager: "Project Manager", ...Object.fromEntries(SPECIALISTS) };

export function roleLabel(role: string): string {
  return LABELS[role] ?? role;
}
