import { Button, Container } from "@/components/ui/ui";

export default function NotFound() {
  return (
    <Container className="flex min-h-[60vh] flex-col items-center justify-center text-center">
      <p className="eyebrow mb-4">404</p>
      <h1 className="h1 text-balance"><span className="text-fade">That page isn’t here.</span></h1>
      <p className="lead mt-4 max-w-md">The link may be old, or the page may have moved.</p>
      <div className="mt-8 flex gap-3"><Button href="/">Back to overview</Button><Button href="/ask" variant="ghost">Ask a question</Button></div>
    </Container>
  );
}
