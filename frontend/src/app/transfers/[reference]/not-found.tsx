import Link from "next/link";

export default function TransferNotFound() {
  return (
    <div className="detail">
      <Link href="/" className="backlink">
        ← All transfers
      </Link>
      <h1>No such transfer</h1>
      <p className="muted">
        That reference does not match any transfer. References look like{" "}
        <code>TRF-</code> followed by sixteen hex characters.
      </p>
    </div>
  );
}
