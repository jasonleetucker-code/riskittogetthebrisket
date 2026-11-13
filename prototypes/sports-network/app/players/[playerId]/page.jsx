import Experience from "../../../components/Experience";
export default async function Player({ params }) {
  const { playerId } = await params;
  return <Experience screen="player" playerId={playerId} />;
}
