import { Grid } from "@mui/material";
import TimeSeriesPanel from "components/metrics/panels/TimeSeriesPanel";
import { useCHContext } from "components/UseClickhouseProvider";
import dayjs from "dayjs";
import { RocksetParam } from "lib/rockset";
import { useState } from "react";
import { RStoCHTimeParams } from "./metrics";

const ROW_HEIGHT = 240;

export default function Kpis() {
  // Looking at data from the past six months
  const [startTime, _setStartTime] = useState(dayjs().subtract(6, "month"));
  const [stopTime, _setStopTime] = useState(dayjs());

  const timeParams: RocksetParam[] = [
    {
      name: "startTime",
      type: "string",
      value: startTime,
    },
    {
      name: "stopTime",
      type: "string",
      value: stopTime,
    },
  ];

  const clickhouseTimeParams = RStoCHTimeParams(timeParams);
  const useCH = useCHContext().useCH;

  return (
    <Grid container spacing={2}>
      <Grid item xs={12} lg={6} height={ROW_HEIGHT}>
        <TimeSeriesPanel
          title={"% of commits red on trunk (Weekly)"}
          queryName={"master_commit_red_percent"}
          queryCollection={"metrics"}
          queryParams={
            useCH
              ? {
                  ...clickhouseTimeParams,
                  granularity: "week",
                  workflowNames: ["lint", "pull", "trunk"],
                }
              : timeParams
          }
          granularity={"week"}
          timeFieldName={"granularity_bucket"}
          yAxisFieldName={"metric"}
          yAxisRenderer={(unit) => {
            return `${unit * 100} %`;
          }}
          groupByFieldName={"name"}
          useClickHouse={useCH}
        />
      </Grid>

      <Grid item xs={12} lg={6} height={ROW_HEIGHT}>
        <TimeSeriesPanel
          title={"# of force merges (Weekly)"}
          queryName={"number_of_force_pushes_historical"}
          queryCollection={"pytorch_dev_infra_kpis"}
          queryParams={clickhouseTimeParams}
          granularity={"week"}
          timeFieldName={"bucket"}
          yAxisFieldName={"count"}
          yAxisRenderer={(unit) => `${unit}`}
          useClickHouse={true}
        />
      </Grid>

      <Grid item xs={12} lg={6} height={ROW_HEIGHT}>
        <TimeSeriesPanel
          title={"Time to Red Signal - (Weekly, pull workflow)"}
          queryName={"ttrs_percentiles"}
          queryParams={{
            ...clickhouseTimeParams,
            one_bucket: false,
            percentile_to_get: 0,
            workflow: "pull",
          }}
          granularity={"week"}
          timeFieldName={"bucket"}
          yAxisFieldName={"ttrs_mins"}
          yAxisRenderer={(duration) => duration}
          useClickHouse={true}
          groupByFieldName="percentile"
          // Format data so that we can display all percentiles in the same
          // chart. Goes from 1 row per timestamp with all percentiles in the
          // row to 4 rows per timestamp with one percentile in each row.
          dataReader={(data) => {
            const percentiles = ["p25", "p50", "p75", "p90"];
            return data
              .map((d) =>
                percentiles.map((p) => {
                  return {
                    ...d,
                    percentile: p,
                    ttrs_mins: d[p],
                  };
                })
              )
              .flat();
          }}
        />
      </Grid>

      <Grid item xs={12} lg={6} height={ROW_HEIGHT}>
        <TimeSeriesPanel
          title={"% of force merges (Weekly, 2 week rolling avg)"}
          queryName={"weekly_force_merge_stats"}
          queryCollection={"commons"}
          queryParams={{
            ...clickhouseTimeParams,
            one_bucket: false,
            merge_type: "",
            granularity: "week",
          }}
          granularity={"week"}
          timeFieldName={"granularity_bucket"}
          yAxisFieldName={"metric"}
          yAxisRenderer={(unit) => {
            return `${unit} %`;
          }}
          groupByFieldName={"name"}
          useClickHouse={true}
        />
      </Grid>

      <Grid item xs={12} lg={6} height={ROW_HEIGHT}>
        <TimeSeriesPanel
          title={"Avg time-to-signal - E2E (Weekly)"}
          queryName={"time_to_signal"}
          queryCollection={"pytorch_dev_infra_kpis"}
          queryParams={useCH ? clickhouseTimeParams : timeParams}
          granularity={"week"}
          timeFieldName={"week_bucket"}
          yAxisFieldName={"avg_tts"}
          yAxisLabel={"Hours"}
          yAxisRenderer={(unit) => `${unit}`}
          groupByFieldName="branch"
          useClickHouse={useCH}
        />
      </Grid>

      <Grid item xs={12} lg={6} height={ROW_HEIGHT}>
        <TimeSeriesPanel
          title={"# of reverts (2 week moving avg)"}
          queryName={"num_reverts"}
          queryCollection={"pytorch_dev_infra_kpis"}
          queryParams={useCH ? clickhouseTimeParams : timeParams}
          granularity={"week"}
          timeFieldName={"bucket"}
          yAxisFieldName={"num"}
          yAxisRenderer={(unit) => `${unit}`}
          groupByFieldName={"code"}
          useClickHouse={useCH}
        />
      </Grid>

      <Grid item xs={12} lg={6} height={ROW_HEIGHT}>
        <TimeSeriesPanel
          title={"viable/strict lag (Daily)"}
          queryName={"strict_lag_historical"}
          queryCollection={"pytorch_dev_infra_kpis"}
          queryParams={{
            ...clickhouseTimeParams,
            // Missing data prior to 2024-10-01 due to migration to ClickHouse
            ...(startTime < dayjs("2024-10-01") && {
              startTime: dayjs("2024-10-01")
                .utc()
                .format("YYYY-MM-DDTHH:mm:ss.SSS"),
            }),
            repoFullName: "pytorch/pytorch",
          }}
          granularity={"day"}
          timeFieldName={"push_time"}
          yAxisFieldName={"diff_hr"}
          yAxisLabel={"Hours"}
          yAxisRenderer={(unit) => `${unit}`}
          // the data is very variable, so set the y axis to be something that makes this chart a bit easier to read
          additionalOptions={{ yAxis: { max: 10 } }}
          useClickHouse={true}
        />
      </Grid>

      <Grid item xs={6} height={ROW_HEIGHT}>
        <TimeSeriesPanel
          title={"Weekly external PR count (4 week moving average)"}
          queryName={"external_contribution_stats"}
          queryParams={clickhouseTimeParams}
          queryCollection={"metrics"}
          granularity={"week"}
          timeFieldName={"granularity_bucket"}
          yAxisFieldName={"pr_count"}
          yAxisRenderer={(value) => value}
          additionalOptions={{ yAxis: { scale: true } }}
          useClickHouse={true}
        />
      </Grid>

      <Grid item xs={6} height={ROW_HEIGHT}>
        <TimeSeriesPanel
          title={"Monthly external PR count"}
          queryName={"monthly_contribution_stats"}
          queryCollection={"pytorch_dev_infra_kpis"}
          queryParams={clickhouseTimeParams}
          granularity={"month"}
          timeFieldName={"year_and_month"}
          timeFieldDisplayFormat={"MMMM YYYY"}
          yAxisFieldName={"pr_count"}
          yAxisRenderer={(value) => value}
          additionalOptions={{ yAxis: { scale: true } }}
          useClickHouse={true}
        />
      </Grid>

      <Grid item xs={12} lg={6} height={ROW_HEIGHT}>
        <TimeSeriesPanel
          title={"Total number of open disabled tests (Daily)"}
          queryName={"disabled_test_historical"}
          queryCollection={"metrics"}
          queryParams={{ ...clickhouseTimeParams, repo: "pytorch/pytorch" }}
          granularity={"day"}
          timeFieldName={"granularity_bucket"}
          yAxisFieldName={"number_of_open_disabled_tests"}
          yAxisRenderer={(duration) => duration}
          useClickHouse={true}
        />
      </Grid>
    </Grid>
  );
}
