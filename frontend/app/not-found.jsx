import { Button } from "@/components/ds/Button";
import { EmptyState } from "@/components/ds/EmptyState";

/**
 * 404 page.  Rendered inside the root layout (so the app shell, nav and
 * tokens are present).  A server component: no client JS beyond the shared
 * primitives.
 */
export const metadata = { title: "Page not found" };

export default function NotFound() {
  return (
    <section className="main-shell" style={{ paddingTop: 40 }}>
      <EmptyState
        title="Page not found"
        description="That page does not exist, or it moved. Check the address, or head back to the dashboard."
        action={
          <Button as="a" href="/" variant="primary">
            Go home
          </Button>
        }
      />
    </section>
  );
}
