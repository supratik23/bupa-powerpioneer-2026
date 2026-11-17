import { useState } from "react";
import { PageHeader, Tabs } from "../../components/ui";
import EmployeesAdmin from "./EmployeesAdmin";
import { QuestionsAdmin, ResponsesAdmin } from "./QuestionsAdmin";
import RiskAdmin from "./RiskAdmin";

type TabId = "employees" | "questions" | "responses" | "risk";

export default function AdminPage() {
  const [tab, setTab] = useState<TabId>("employees");
  return (
    <main className="page-shell">
      <PageHeader
        kicker="Staff only"
        title="Administration"
        description="Manage the employee directory, pulse survey questions and calculated wellbeing records."
      />
      <Tabs
        tabs={[
          { id: "employees", label: "Employees" },
          { id: "questions", label: "Questions" },
          { id: "responses", label: "Responses" },
          { id: "risk", label: "Risk data" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "employees" && <EmployeesAdmin />}
      {tab === "questions" && <QuestionsAdmin />}
      {tab === "responses" && <ResponsesAdmin />}
      {tab === "risk" && <RiskAdmin />}
    </main>
  );
}
