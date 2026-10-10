import { useOutletContext } from "react-router-dom";
import type { PropsContext } from "./pageContext";
import { PropBoard } from "./PropBoard";

/** The props tab, the same for skaters and goalies. */
export const PlayerPropsPanel = () => {
  const { data } = useOutletContext<PropsContext>();
  return (
    <section className="bd-section" aria-labelledby="props-h">
      <div className="bd-section-head">
        <h2 className="bd-heading" id="props-h">Props on the board</h2>
        <div className="bd-legend">
          <span><i className="bd-swatch" style={{ background: "var(--ink)", borderRadius: "50%" }} />Model's chance</span>
          <span><i className="bd-swatch" style={{ borderLeft: "2px dashed var(--goal-red)", width: 2 }} />Book's implied chance</span>
          <span><i className="bd-swatch" style={{ background: "var(--ink)", borderRadius: 4 }} />Edge 3 pts or more</span>
        </div>
      </div>
      {data.props.length ? (
        <>
          <PropBoard props={data.props} />
          <p className="pl-caption">
            Edge is the model's expected return at the best price, in points. Prices are the best across the consensus
            books; markets PropLine doesn't carry (hits) come from ESPN's feed, one book only.
          </p>
        </>
      ) : (
        <div className="bd-empty">No lines posted for the next game yet.</div>
      )}
    </section>
  );
};
