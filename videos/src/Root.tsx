import { Composition } from "remotion";
import { Launch, type LaunchProps } from "./videos/launch/Launch";
import { DURATION } from "./videos/launch/cues";
import { Launch2, type Launch2Props } from "./videos/launch2/Launch2";
import { DURATION as DURATION2 } from "./videos/launch2/cues";
import { Launch3, type Launch3Props } from "./videos/launch3/Launch3";
import { DURATION as DURATION3 } from "./videos/launch3/cues";

export const Root = () => (
  <>
    <Composition
      id="Launch"
      component={Launch}
      width={1920}
      height={1080}
      fps={60}
      durationInFrames={Math.round(DURATION * 60)}
      defaultProps={{ fps: 60, debug: false } satisfies LaunchProps}
      calculateMetadata={({ props }) => ({ fps: props.fps, durationInFrames: Math.round(DURATION * props.fps) })}
    />
    <Composition
      id="Launch2"
      component={Launch2}
      width={1920}
      height={1080}
      fps={60}
      durationInFrames={Math.round(DURATION2 * 60)}
      defaultProps={{ fps: 60, debug: false } satisfies Launch2Props}
      calculateMetadata={({ props }) => ({ fps: props.fps, durationInFrames: Math.round(DURATION2 * props.fps) })}
    />
    <Composition
      id="Launch3"
      component={Launch3}
      width={1920}
      height={1080}
      fps={60}
      durationInFrames={Math.round(DURATION3 * 60)}
      defaultProps={{ fps: 60, debug: false } satisfies Launch3Props}
      calculateMetadata={({ props }) => ({ fps: props.fps, durationInFrames: Math.round(DURATION3 * props.fps) })}
    />
  </>
);
