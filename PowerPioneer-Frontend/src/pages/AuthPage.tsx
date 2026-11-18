import { useState } from "react";
import type { FormEvent } from "react";
import { Activity, ArrowRight } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { EMPLOYMENT_TYPES } from "../api/types";
import type { EmploymentType, RegisterPayload } from "../api/types";
import { label } from "../lib/format";
import { useAction } from "../lib/useAsync";
import { ErrorNote, SelectField, Tabs, TextField, enumOptions } from "../components/ui";

type Mode = "login" | "signup";

function Brand() {
  return (
    <div className="brand-mark">
      <div className="pulse-mark">
        <Activity size={23} strokeWidth={2.3} />
      </div>
      <div>
        <strong>ShiftGuard</strong>
        <span>Frontline wellbeing</span>
      </div>
    </div>
  );
}

function LoginForm({ onSwitch }: { onSwitch: () => void }) {
  const { login } = useAuth();
  const { busy, error, run } = useAction();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(() => login(email.trim(), password));
  };

  return (
    <form className="pp-form" onSubmit={submit}>
      <TextField full label="Work email" type="email" value={email} onChange={setEmail} required autoComplete="email" />
      <TextField
        full
        label="Password"
        type="password"
        value={password}
        onChange={setPassword}
        required
        autoComplete="current-password"
      />
      <ErrorNote message={error} />
      <div className="pp-form-actions">
        <button className="primary-button full" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"} <ArrowRight size={16} />
        </button>
      </div>
      <p className="pp-auth-switch full">
        New to ShiftGuard?{" "}
        <button type="button" className="pp-link" onClick={onSwitch}>
          Create an account
        </button>
      </p>
    </form>
  );
}

const emptyRegistration: RegisterPayload = {
  employee_number: "",
  first_name: "",
  last_name: "",
  email: "",
  password: "",
  job_role: "",
  department: "",
  location: "",
  employment_type: "FULL_TIME",
  contracted_weekly_hours: null,
  hire_date: null,
};

function SignUpForm({ onSwitch }: { onSwitch: () => void }) {
  const { register } = useAuth();
  const { busy, error, setError, run } = useAction();
  const [form, setForm] = useState<RegisterPayload>(emptyRegistration);
  const [confirm, setConfirm] = useState("");

  const set = <K extends keyof RegisterPayload>(key: K, value: RegisterPayload[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (form.password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    void run(() =>
      register({
        ...form,
        email: form.email.trim(),
        department: form.department || null,
        location: form.location || null,
        hire_date: form.hire_date || null,
        contracted_weekly_hours:
          form.contracted_weekly_hours === null || String(form.contracted_weekly_hours) === ""
            ? null
            : Number(form.contracted_weekly_hours),
      }),
    );
  };

  return (
    <form className="pp-form" onSubmit={submit}>
      <TextField label="First name" value={form.first_name} onChange={(v) => set("first_name", v)} required />
      <TextField label="Last name" value={form.last_name} onChange={(v) => set("last_name", v)} required />
      <TextField
        label="Work email"
        type="email"
        value={form.email}
        onChange={(v) => set("email", v)}
        required
        autoComplete="email"
      />
      <TextField
        label="Employee number"
        value={form.employee_number}
        onChange={(v) => set("employee_number", v)}
        required
      />
      <TextField label="Job role" value={form.job_role} onChange={(v) => set("job_role", v)} required />
      <SelectField
        label="Employment type"
        value={form.employment_type}
        onChange={(v) => set("employment_type", v as EmploymentType)}
        options={enumOptions(EMPLOYMENT_TYPES, label)}
        required
      />
      <TextField label="Department" value={form.department} onChange={(v) => set("department", v)} />
      <TextField label="Location" value={form.location} onChange={(v) => set("location", v)} />
      <TextField
        label="Contracted weekly hours"
        type="number"
        min={0}
        step="0.5"
        value={form.contracted_weekly_hours}
        onChange={(v) => set("contracted_weekly_hours", v === "" ? null : Number(v))}
      />
      <TextField label="Hire date" type="date" value={form.hire_date} onChange={(v) => set("hire_date", v)} />
      <TextField
        label="Password"
        type="password"
        value={form.password}
        onChange={(v) => set("password", v)}
        required
        autoComplete="new-password"
        hint="At least 8 characters, not too common or similar to your details."
      />
      <TextField
        label="Confirm password"
        type="password"
        value={confirm}
        onChange={setConfirm}
        required
        autoComplete="new-password"
      />
      <ErrorNote message={error} />
      <div className="pp-form-actions">
        <button className="primary-button full" type="submit" disabled={busy}>
          {busy ? "Creating account…" : "Create account"} <ArrowRight size={16} />
        </button>
      </div>
      <p className="pp-auth-switch full">
        Already registered?{" "}
        <button type="button" className="pp-link" onClick={onSwitch}>
          Sign in
        </button>
      </p>
    </form>
  );
}

export default function AuthPage() {
  const [mode, setMode] = useState<Mode>("login");

  return (
    <main className="pp-auth">
      <section className="surface pp-auth-card">
        <Brand />
        <Tabs
          tabs={[
            { id: "login", label: "Sign in" },
            { id: "signup", label: "Sign up" },
          ]}
          value={mode}
          onChange={setMode}
        />
        <h1>{mode === "login" ? "Welcome back." : "Create your account."}</h1>
        <p>
          {mode === "login"
            ? "Sign in to see your shift and private wellbeing check-ins."
            : "Register as a team member. Your manager can link you to your team afterwards."}
        </p>
        {mode === "login" ? (
          <LoginForm onSwitch={() => setMode("signup")} />
        ) : (
          <SignUpForm onSwitch={() => setMode("login")} />
        )}
      </section>
    </main>
  );
}
