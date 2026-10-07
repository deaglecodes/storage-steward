import { AbsoluteFill, Html5Audio, Sequence, staticFile, useVideoConfig } from "remotion";

import { TargetLog } from "../../kit/debug";
import { useTime } from "../../kit/time";
import { C, FONT } from "../launch/tokens";
import { ChoreAct, OpenAct, PunchAct } from "./acts1";
import { HubAct } from "./acts2";
import { EndAct, FULL_HIT, ProofAct, RulesAct } from "./acts3";
import { ASKS, b, PULSE, SWEEPS } from "./cues";
import { Atmosphere } from "./fx";

export type Launch2Props = { fps: number; debug: boolean };

type Hit = [name: string, at: number, volume: number];
const MIX = 0.6;   // master gain: the impacts land on the score's loudest beats, so leave headroom (the render limiter does the rest)
const SFX: Hit[] = [
  ["whoosh", b(2, 4) - 0.12, 0.5], ["impact", b(4, 1), 0.45], ["whoosh", b(4, 4), 0.4],
  ...[0, 1, 2, 3].map((k): Hit => ["impact", b(5, k + 1), 0.4]),
  ["shimmer", b(6, 4), 0.5],
  ...Array.from({ length: 12 }, (_, i): Hit => ["tick", b(7) + 0.05 + i * 0.05, 0.12]),
  ["impact", b(7, 3), 0.3],
  ...[0, 1, 2, 3].map((k): Hit => ["ping", b(8, k + 1), 0.25]),
  ...SWEEPS.map(([e]): Hit => ["ping", e + PULSE, 0.1]),
  ["whoosh", b(12, 4) - 0.1, 0.55],
  ...ASKS.flatMap((ask, k) => Array.from({ length: Math.ceil(ask.say.length / 2) }, (_, i): Hit => ["tick", b(13 + k, 1, 0.5) + i * 0.056, 0.07])),
  ...ASKS.map((_, k): Hit => ["flip", b(13 + k, 3, 0.6), 0.35]),
  ...ASKS.map((_, k): Hit => ["ping", b(13 + k, 3, 0.6), 0.16]),
  ["whoosh", b(16, 4), 0.6], ["impact", FULL_HIT, 0.4],
  ...[0, 1, 2, 3].map((k): Hit => ["impact", b(19, k + 1), 0.35]),
  ["whoosh", b(20), 0.35], ["whoosh", b(20, 4), 0.45],
  ["shimmer", b(21, 2), 0.4], ["impact", b(24), 0.35],
];

export const Launch2 = ({ debug }: Launch2Props) => {
  const t = useTime();
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: C.bg, color: C.ink, fontFamily: FONT.body, overflow: "hidden" }}>
      <OpenAct t={t} />
      <PunchAct t={t} />
      <ChoreAct t={t} />
      <HubAct t={t} />
      <RulesAct t={t} />
      <ProofAct t={t} />
      <EndAct t={t} />
      <Atmosphere t={t} />
      <Html5Audio src={staticFile("audio/launch2/music/launch2.wav")} volume={MIX} />
      {SFX.map(([name, at, volume], i) => (
        <Sequence key={i} from={Math.max(0, Math.round(at * fps))} durationInFrames={Math.round(1.2 * fps)}>
          <Html5Audio src={staticFile(`audio/launch2/sfx/${name}.wav`)} volume={volume * MIX} />
        </Sequence>
      ))}
      {debug ? <TargetLog /> : null}
    </AbsoluteFill>
  );
};
