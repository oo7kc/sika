//+------------------------------------------------------------------+
//|                                             SikaHistoryProbe.mq5 |
//| Read-only Exness XAUUSDm historical availability probe           |
//+------------------------------------------------------------------+
#property copyright "Sika"
#property version   "1.000"
#property description "Probes M1/M15/H1 availability near the five-year boundary."
#property description "Writes metadata only; it cannot place or manage orders."
#property script_show_inputs

input string   InpSymbol             = "XAUUSDm";
input datetime InpTargetStart        = D'2021.10.01 00:00:00';
input int      InpProbeWindowDays    = 7;
input int      InpLoadTimeoutSeconds = 60;

const string EXPECTED_SYMBOL = "XAUUSDm";
const string ACCOUNT_PROFILE = "Standard";
const string PROFILE_SOURCE  = "research-contract-v0.1";
const string OUTPUT_ROOT     = "Sika\\probes";

struct SeriesProbe
  {
   string label;
   int    timeframe_seconds;
   int    window_bar_count;
   long   window_first_time;
   long   window_last_time;
   long   loaded_first_time;
   long   terminal_first_time;
   long   server_first_time;
   long   loaded_bar_count;
   bool   synchronized;
   bool   target_window_available;
  };

string JsonString(const string value)
  {
   string escaped=value;
   StringReplace(escaped,"\\","\\\\");
   StringReplace(escaped,"\"","\\\"");
   StringReplace(escaped,"\r","\\r");
   StringReplace(escaped,"\n","\\n");
   StringReplace(escaped,"\t","\\t");
   return "\""+escaped+"\"";
  }

string JsonBool(const bool value)
  {
   return value ? "true" : "false";
  }

string JsonLong(const long value)
  {
   return StringFormat("%I64d",value);
  }

string BuildProbeId(const datetime generated_at)
  {
   MqlDateTime parts;
   TimeToStruct(generated_at,parts);
   return StringFormat("%04d%02d%02dT%02d%02d%02dZ",
                       parts.year,parts.mon,parts.day,
                       parts.hour,parts.min,parts.sec);
  }

bool ProbeSeries(const ENUM_TIMEFRAMES timeframe,
                 const string label,
                 const datetime target_end,
                 SeriesProbe &probe)
  {
   MqlRates rates[];
   ArraySetAsSeries(rates,false);
   const ulong started=GetTickCount64();
   const ulong timeout_ms=(ulong)InpLoadTimeoutSeconds*1000;
   int copied=-1;
   bool synchronized=false;

   while(!IsStopped())
     {
      ResetLastError();
      copied=CopyRates(InpSymbol,timeframe,InpTargetStart,target_end,rates);
      synchronized=(bool)SeriesInfoInteger(
         InpSymbol,timeframe,SERIES_SYNCHRONIZED);
      if(copied>=0 && synchronized)
         break;
      if(GetTickCount64()-started>=timeout_ms)
        {
         PrintFormat(
            "Sika history probe failed for %s after %d seconds "
            "(copied=%d, synchronized=%s, error=%d).",
            label,InpLoadTimeoutSeconds,copied,
            (synchronized ? "true" : "false"),GetLastError());
         return false;
        }
      Sleep(500);
     }

   if(IsStopped())
     {
      Print("Sika history probe cancelled by the user.");
      return false;
     }

   probe.label=label;
   probe.timeframe_seconds=PeriodSeconds(timeframe);
   probe.window_bar_count=MathMax(copied,0);
   probe.window_first_time=(copied>0 ? (long)rates[0].time : 0);
   probe.window_last_time=(copied>0 ? (long)rates[copied-1].time : 0);
   probe.loaded_first_time=SeriesInfoInteger(
      InpSymbol,timeframe,SERIES_FIRSTDATE);
   probe.terminal_first_time=SeriesInfoInteger(
      InpSymbol,timeframe,SERIES_TERMINAL_FIRSTDATE);
   probe.server_first_time=SeriesInfoInteger(
      InpSymbol,timeframe,SERIES_SERVER_FIRSTDATE);
   probe.loaded_bar_count=SeriesInfoInteger(
      InpSymbol,timeframe,SERIES_BARS_COUNT);
   probe.synchronized=synchronized;
   probe.target_window_available=(copied>0);

   PrintFormat(
      "Sika %s probe: target_window_available=%s, bars=%d, "
      "server_first=%s, terminal_first=%s.",
      label,(probe.target_window_available ? "true" : "false"),copied,
      TimeToString((datetime)probe.server_first_time,TIME_DATE|TIME_MINUTES),
      TimeToString((datetime)probe.terminal_first_time,TIME_DATE|TIME_MINUTES));
   return true;
  }

string SeriesJson(const SeriesProbe &probe)
  {
   string value="{\n";
   value+="      \"timeframe_seconds\": "+JsonLong(probe.timeframe_seconds)+",\n";
   value+="      \"target_window_available\": "+
          JsonBool(probe.target_window_available)+",\n";
   value+="      \"window_bar_count\": "+JsonLong(probe.window_bar_count)+",\n";
   value+="      \"window_first_time_epoch\": "+
          JsonLong(probe.window_first_time)+",\n";
   value+="      \"window_last_time_epoch\": "+
          JsonLong(probe.window_last_time)+",\n";
   value+="      \"loaded_first_time_epoch\": "+
          JsonLong(probe.loaded_first_time)+",\n";
   value+="      \"terminal_first_time_epoch\": "+
          JsonLong(probe.terminal_first_time)+",\n";
   value+="      \"server_first_time_epoch\": "+
          JsonLong(probe.server_first_time)+",\n";
   value+="      \"loaded_bar_count\": "+JsonLong(probe.loaded_bar_count)+",\n";
   value+="      \"synchronized\": "+JsonBool(probe.synchronized)+"\n";
   value+="    }";
   return value;
  }

bool WriteProbe(const string probe_id,
                const datetime generated_at,
                const datetime target_end,
                const SeriesProbe &m1,
                const SeriesProbe &m15,
                const SeriesProbe &h1)
  {
   const bool five_year_boundary_available=
      m1.target_window_available &&
      m15.target_window_available &&
      h1.target_window_available;

   string manifest="{\n";
   manifest+="  \"schema_version\": 2,\n";
   manifest+="  \"complete\": true,\n";
   manifest+="  \"mode\": \"read-only\",\n";
   manifest+="  \"probe_type\": \"history-availability\",\n";
   manifest+="  \"probe_id\": "+JsonString(probe_id)+",\n";
   manifest+="  \"generated_at_epoch\": "+JsonLong((long)generated_at)+",\n";
   manifest+="  \"requested_start_epoch\": "+
             JsonLong((long)InpTargetStart)+",\n";
   manifest+="  \"requested_end_epoch\": "+JsonLong((long)target_end)+",\n";
   manifest+="  \"five_year_boundary_available\": "+
             JsonBool(five_year_boundary_available)+",\n";
   manifest+="  \"terminal\": {\n";
   manifest+="    \"build\": "+
             JsonLong(TerminalInfoInteger(TERMINAL_BUILD))+",\n";
   manifest+="    \"max_bars\": "+
             JsonLong(TerminalInfoInteger(TERMINAL_MAXBARS))+",\n";
   manifest+="    \"connected\": "+JsonBool(
      (bool)TerminalInfoInteger(TERMINAL_CONNECTED))+"\n";
   manifest+="  },\n";
   manifest+="  \"account\": {\n";
   manifest+="    \"server\": "+
             JsonString(AccountInfoString(ACCOUNT_SERVER))+",\n";
   manifest+="    \"company\": "+
             JsonString(AccountInfoString(ACCOUNT_COMPANY))+",\n";
   manifest+="    \"trade_mode\": \"demo\",\n";
   manifest+="    \"profile\": "+JsonString(ACCOUNT_PROFILE)+",\n";
   manifest+="    \"profile_source\": "+JsonString(PROFILE_SOURCE)+"\n";
   manifest+="  },\n";
   manifest+="  \"symbol\": "+JsonString(InpSymbol)+",\n";
   manifest+="  \"series\": {\n";
   manifest+="    \"M1\": "+SeriesJson(m1)+",\n";
   manifest+="    \"M15\": "+SeriesJson(m15)+",\n";
   manifest+="    \"H1\": "+SeriesJson(h1)+"\n";
   manifest+="  }\n";
   manifest+="}\n";

   const string file_name=probe_id+"_"+InpSymbol+"_history_probe.json";
   const string relative_path=OUTPUT_ROOT+"\\"+file_name;
   ResetLastError();
   const int handle=FileOpen(
      relative_path,FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(handle==INVALID_HANDLE)
     {
      PrintFormat("Sika history probe cannot open %s (error=%d).",
                  relative_path,GetLastError());
      return false;
     }
   const bool ok=(FileWriteString(handle,manifest)==StringLen(manifest));
   FileFlush(handle);
   FileClose(handle);
   if(!ok)
     {
      PrintFormat("Sika history probe failed writing %s (error=%d).",
                  relative_path,GetLastError());
      return false;
     }

   PrintFormat("Sika history availability probe complete: %s\\%s",
               OUTPUT_ROOT,file_name);
   return true;
  }

void OnStart()
  {
   if(InpSymbol!=EXPECTED_SYMBOL)
     {
      PrintFormat("Sika history probe rejected: symbol must be exactly %s.",
                  EXPECTED_SYMBOL);
      return;
     }
   if(InpProbeWindowDays<1 || InpProbeWindowDays>31)
     {
      Print("Sika history probe rejected: window must be between 1 and 31 days.");
      return;
     }
   if(InpLoadTimeoutSeconds<5 || InpLoadTimeoutSeconds>300)
     {
      Print("Sika history probe rejected: timeout must be between 5 and 300 seconds.");
      return;
     }
   if(!(bool)TerminalInfoInteger(TERMINAL_CONNECTED))
     {
      Print("Sika history probe rejected: MT5 is disconnected.");
      return;
     }
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO)
     {
      Print("Sika history probe rejected: v0 only permits a demo account.");
      return;
     }
   if(StringFind(AccountInfoString(ACCOUNT_COMPANY),"Exness")<0)
     {
      Print("Sika history probe rejected: the connected account is not Exness.");
      return;
     }
   if(!SymbolSelect(InpSymbol,true))
     {
      PrintFormat("Sika history probe cannot enable %s (error=%d).",
                  InpSymbol,GetLastError());
      return;
     }

   const datetime generated_at=TimeGMT();
   const datetime target_end=InpTargetStart+(InpProbeWindowDays*24*60*60)-1;
   if(InpTargetStart<=0 || target_end>=generated_at)
     {
      Print("Sika history probe rejected: target window must be in the past.");
      return;
     }

   SeriesProbe m1;
   SeriesProbe m15;
   SeriesProbe h1;
   if(!ProbeSeries(PERIOD_M1,"M1",target_end,m1))
      return;
   if(!ProbeSeries(PERIOD_M15,"M15",target_end,m15))
      return;
   if(!ProbeSeries(PERIOD_H1,"H1",target_end,h1))
      return;

   WriteProbe(BuildProbeId(generated_at),generated_at,target_end,m1,m15,h1);
  }
