import Workspace from "@/components/workspace";

// Read at request time so one built image can run in either mode.
export const dynamic = "force-dynamic";

export default function Home() {
  const mode = process.env.DATA_MODE || process.env.NEXT_PUBLIC_DATA_MODE;
  return <Workspace dataMode={mode === "api" ? "api" : "demo"} />;
}
