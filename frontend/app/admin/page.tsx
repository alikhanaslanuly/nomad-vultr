import Link from "next/link";

export default function AdminPage() {
  return (
    <section className="simple-page">
      <p className="eyebrow">OPERATOR / UNAVAILABLE</p>
      <h1>Operator access.</h1>
      <div className="panel report-notes">
        <h2>Awaiting backend integration</h2>
        <p>
          Operator controls are unavailable until the team confirms the instances response
          and server-side authorization. No admin token is collected here.
        </p>
        <p>
          The browser is not an authentication authority. Kill operations require an
          authorized backend and explicit confirmation.
        </p>
      </div>
      <Link className="primary-button" href="/">
        Back to analysis →
      </Link>
    </section>
  );
}
