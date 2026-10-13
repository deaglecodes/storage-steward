import { AbsoluteFill, Html5Audio, staticFile } from "remotion";

import { useTime } from "../../kit/time";
import { Clone, End, Forget, Less, Mess, Proof, Rules } from "./scenes";
import { L } from "./theme";

export type Launch3Props = { fps: number; debug: boolean };

/** The minimal cut: a page that fills with agent leftovers, gets swept clean, and stays light. */
export const Launch3 = (_props: Launch3Props) => {
  const t = useTime();
  return (
    <AbsoluteFill style={{ background: L.paper, overflow: "hidden" }}>
      <Mess t={t} />
      <Less t={t} />
      <Clone t={t} />
      <Forget t={t} />
      <Rules t={t} />
      <Proof t={t} />
      <End t={t} />
      <Html5Audio src={staticFile("audio/launch3/music/launch3.wav")} />
    </AbsoluteFill>
  );
};
