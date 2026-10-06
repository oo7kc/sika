//+------------------------------------------------------------------+
//|                                               SikaExportBars.mq5 |
//| Read-only Exness XAUUSDm bar exporter for the Sika research path |
//+------------------------------------------------------------------+
#property copyright "Sika"
#property version   "1.000"
#property description "Exports closed XAUUSDm M15/H1 bars and a redacted manifest."
#property description "This script contains no order-placement or position-management code."
#property script_show_inputs

input string InpSymbol             = "XAUUSDm";
input int    InpM15Bars            = 5000;
input int    InpH1Bars             = 2000;
input int    InpLoadTimeoutSeconds = 30;

const string EXPECTED_SYMBOL = "XAUUSDm";
const string ACCOUNT_PROFILE = "Standard";
const string PROFILE_SOURCE  = "research-contract-v0.1";
const string OUTPUT_ROOT     = "Sika\\exports";
const int    MIN_BAR_COUNT   = 100;
const int    MAX_BAR_COUNT   = 100000;

struct ExportStats
  {
   string file_name;
   int    count;
   long   first_time;
   long   last_time;
   int    timeframe_seconds;
  };

//+------------------------------------------------------------------+
//| Escape a value for the small JSON manifest written by the script. |
//+------------------------------------------------------------------+
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

string JsonDouble(const double value,const int precision)
  {
   return DoubleToString(value,precision);
  }

//+------------------------------------------------------------------+
//| Build a filesystem-safe, UTC-labelled export identifier.         |
//+------------------------------------------------------------------+
string BuildExportId(const datetime generated_at)
  {
   MqlDateTime parts;
   TimeToStruct(generated_at,parts);
   return StringFormat("%04d%02d%02dT%02d%02d%02dZ",
                       parts.year,parts.mon,parts.day,
                       parts.hour,parts.min,parts.sec);
  }

//+------------------------------------------------------------------+
//| Check that a requested bar count is deliberate and bounded.      |
//+------------------------------------------------------------------+
bool ValidBarCount(const string label,const int count)
  {
   if(count<MIN_BAR_COUNT || count>MAX_BAR_COUNT)
     {
      PrintFormat("Sika export rejected: %s bar count %d is outside [%d, %d].",
                  label,count,MIN_BAR_COUNT,MAX_BAR_COUNT);
      return false;
     }
   return true;
  }

//+------------------------------------------------------------------+
//| Load an exact number of closed bars, waiting for synchronization. |
//+------------------------------------------------------------------+
bool LoadClosedRates(const ENUM_TIMEFRAMES timeframe,
                     const string label,
                     const int requested,
                     MqlRates &rates[])
  {
   ArraySetAsSeries(rates,false);
   const ulong started=GetTickCount64();
   const ulong timeout_ms=(ulong)InpLoadTimeoutSeconds*1000;
   int copied=-1;

   while(!IsStopped())
     {
      ResetLastError();
      // start_pos=1 is intentional: position 0 is the still-forming bar.
      copied=CopyRates(InpSymbol,timeframe,1,requested,rates);
      const bool synchronized=(bool)SeriesInfoInteger(
         InpSymbol,timeframe,SERIES_SYNCHRONIZED);

      if(copied==requested && synchronized)
         break;

      if(GetTickCount64()-started>=timeout_ms)
        {
         PrintFormat(
            "Sika export failed: requested %d closed %s bars, received %d "
            "(synchronized=%s, error=%d). Open the chart, load more history, "
            "and run the script again.",
            requested,label,copied,(synchronized ? "true" : "false"),
            GetLastError());
         return false;
        }
      Sleep(500);
     }

   if(IsStopped())
     {
      Print("Sika export cancelled by the user.");
      return false;
     }

   if(ArraySize(rates)!=requested)
     {
      PrintFormat("Sika export failed: %s array size is %d, expected %d.",
                  label,ArraySize(rates),requested);
      return false;
     }

   const datetime newest_closed=iTime(InpSymbol,timeframe,1);
   if(newest_closed<=0 || rates[requested-1].time!=newest_closed)
     {
      PrintFormat(
         "Sika export failed: newest %s bar does not match the terminal's "
         "latest closed bar.",label);
      return false;
     }

   for(int i=0;i<requested;i++)
     {
      const MqlRates row=rates[i];
      if(row.time<=0 ||
         !MathIsValidNumber(row.open) || !MathIsValidNumber(row.high) ||
         !MathIsValidNumber(row.low)  || !MathIsValidNumber(row.close) ||
         row.open<=0 || row.high<=0 || row.low<=0 || row.close<=0 ||
         row.low>MathMin(row.open,row.close) ||
         row.high<MathMax(row.open,row.close) || row.high<row.low ||
         row.tick_volume<0 || row.real_volume<0 || row.spread<0)
        {
         PrintFormat("Sika export failed: invalid %s bar at index %d.",label,i);
         return false;
        }
      if(i>0 && row.time<=rates[i-1].time)
        {
         PrintFormat(
            "Sika export failed: %s timestamps are not strictly increasing "
            "at index %d.",label,i);
         return false;
        }
     }
   return true;
  }

//+------------------------------------------------------------------+
//| Write validated bars in chronological order to UTF-8 CSV.        |
//+------------------------------------------------------------------+
bool WriteRatesCsv(const string export_id,
                   const string label,
                   const ENUM_TIMEFRAMES timeframe,
                   const int digits,
                   MqlRates &rates[],
                   ExportStats &stats)
  {
   const string base_name=export_id+"_"+InpSymbol+"_"+label+".csv";
   const string relative_path=OUTPUT_ROOT+"\\"+base_name;
   ResetLastError();
   const int handle=FileOpen(
      relative_path,FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(handle==INVALID_HANDLE)
     {
      PrintFormat("Sika export failed: cannot open %s (error=%d).",
                  relative_path,GetLastError());
      return false;
     }

   bool ok=(FileWrite(handle,
                      "time_epoch","open","high","low","close",
                      "tick_volume","spread_points","real_volume")>0);
   const int count=ArraySize(rates);
   for(int i=0;i<count && ok;i++)
     {
      ok=(FileWrite(handle,
                    (long)rates[i].time,
                    DoubleToString(rates[i].open,digits),
                    DoubleToString(rates[i].high,digits),
                    DoubleToString(rates[i].low,digits),
                    DoubleToString(rates[i].close,digits),
                    rates[i].tick_volume,
                    rates[i].spread,
                    rates[i].real_volume)>0);
     }
   FileFlush(handle);
   FileClose(handle);

   if(!ok)
     {
      PrintFormat("Sika export failed while writing %s (error=%d).",
                  relative_path,GetLastError());
      return false;
     }

   stats.file_name=base_name;
   stats.count=count;
   stats.first_time=(long)rates[0].time;
   stats.last_time=(long)rates[count-1].time;
   stats.timeframe_seconds=PeriodSeconds(timeframe);
   return true;
  }

//+------------------------------------------------------------------+
//| Write the manifest last; its presence marks a complete export.   |
//+------------------------------------------------------------------+
bool WriteManifest(const string export_id,
                   const datetime generated_at,
                   const int digits,
                   const double point,
                   const MqlTick &tick,
                   const ExportStats &m15,
                   const ExportStats &h1)
  {
   const long server_time=(long)TimeTradeServer();
   const long gmt_time=(long)generated_at;
   string manifest="{\n";
   manifest+="  \"schema_version\": 2,\n";
   manifest+="  \"complete\": true,\n";
   manifest+="  \"mode\": \"read-only\",\n";
   manifest+="  \"export_id\": "+JsonString(export_id)+",\n";
   manifest+="  \"generated_at_epoch\": "+JsonLong(gmt_time)+",\n";
   manifest+="  \"time_basis\": {\n";
   manifest+="    \"bar_time\": \"MT5 trade-server epoch; Exness v0 contract requires UTC\",\n";
   manifest+="    \"server_clock_source\": \"TimeTradeServer\",\n";
   manifest+="    \"server_time_epoch\": "+JsonLong(server_time)+",\n";
   manifest+="    \"server_minus_gmt_seconds\": "+JsonLong(server_time-gmt_time)+"\n";
   manifest+="  },\n";
   manifest+="  \"terminal\": {\n";
   manifest+="    \"name\": "+JsonString(TerminalInfoString(TERMINAL_NAME))+",\n";
   manifest+="    \"company\": "+JsonString(TerminalInfoString(TERMINAL_COMPANY))+",\n";
   manifest+="    \"build\": "+JsonLong(TerminalInfoInteger(TERMINAL_BUILD))+",\n";
   manifest+="    \"connected\": "+JsonBool(
      (bool)TerminalInfoInteger(TERMINAL_CONNECTED))+"\n";
   manifest+="  },\n";
   manifest+="  \"account\": {\n";
   manifest+="    \"server\": "+JsonString(AccountInfoString(ACCOUNT_SERVER))+",\n";
   manifest+="    \"company\": "+JsonString(AccountInfoString(ACCOUNT_COMPANY))+",\n";
   manifest+="    \"currency\": "+JsonString(AccountInfoString(ACCOUNT_CURRENCY))+",\n";
   manifest+="    \"trade_mode\": \"demo\",\n";
   manifest+="    \"profile\": "+JsonString(ACCOUNT_PROFILE)+",\n";
   manifest+="    \"profile_source\": "+JsonString(PROFILE_SOURCE)+"\n";
   manifest+="  },\n";
   manifest+="  \"symbol\": {\n";
   manifest+="    \"name\": "+JsonString(InpSymbol)+",\n";
   manifest+="    \"description\": "+JsonString(
      SymbolInfoString(InpSymbol,SYMBOL_DESCRIPTION))+",\n";
   manifest+="    \"digits\": "+IntegerToString(digits)+",\n";
   manifest+="    \"point\": "+JsonDouble(point,digits)+",\n";
   manifest+="    \"contract_size\": "+JsonDouble(
      SymbolInfoDouble(InpSymbol,SYMBOL_TRADE_CONTRACT_SIZE),4)+",\n";
   manifest+="    \"volume_min\": "+JsonDouble(
      SymbolInfoDouble(InpSymbol,SYMBOL_VOLUME_MIN),4)+",\n";
   manifest+="    \"volume_step\": "+JsonDouble(
      SymbolInfoDouble(InpSymbol,SYMBOL_VOLUME_STEP),4)+",\n";
   manifest+="    \"volume_max\": "+JsonDouble(
      SymbolInfoDouble(InpSymbol,SYMBOL_VOLUME_MAX),4)+"\n";
   manifest+="  },\n";
   manifest+="  \"latest_tick\": {\n";
   manifest+="    \"time_msc\": "+StringFormat("%I64d",(long)tick.time_msc)+",\n";
   manifest+="    \"bid\": "+JsonDouble(tick.bid,digits)+",\n";
   manifest+="    \"ask\": "+JsonDouble(tick.ask,digits)+"\n";
   manifest+="  },\n";
   manifest+="  \"bars\": {\n";
   manifest+="    \"M15\": {\"file\": "+JsonString(m15.file_name)+
             ", \"count\": "+IntegerToString(m15.count)+
             ", \"timeframe_seconds\": "+IntegerToString(m15.timeframe_seconds)+
             ", \"first_time_epoch\": "+JsonLong(m15.first_time)+
             ", \"last_time_epoch\": "+JsonLong(m15.last_time)+
             ", \"forming_bar_excluded\": true},\n";
   manifest+="    \"H1\": {\"file\": "+JsonString(h1.file_name)+
             ", \"count\": "+IntegerToString(h1.count)+
             ", \"timeframe_seconds\": "+IntegerToString(h1.timeframe_seconds)+
             ", \"first_time_epoch\": "+JsonLong(h1.first_time)+
             ", \"last_time_epoch\": "+JsonLong(h1.last_time)+
             ", \"forming_bar_excluded\": true}\n";
   manifest+="  }\n";
   manifest+="}\n";

   const string manifest_name=export_id+"_"+InpSymbol+"_manifest.json";
   const string relative_path=OUTPUT_ROOT+"\\"+manifest_name;
   ResetLastError();
   const int handle=FileOpen(
      relative_path,FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(handle==INVALID_HANDLE)
     {
      PrintFormat("Sika export failed: cannot open manifest %s (error=%d).",
                  relative_path,GetLastError());
      return false;
     }

   const bool ok=(FileWriteString(handle,manifest)==StringLen(manifest));
   FileFlush(handle);
   FileClose(handle);
   if(!ok)
     {
      PrintFormat("Sika export failed while writing manifest %s (error=%d).",
                  relative_path,GetLastError());
      return false;
     }

   PrintFormat("Sika read-only export complete: %s\\%s",OUTPUT_ROOT,manifest_name);
   PrintFormat("Full sandbox path: %s\\MQL5\\Files\\%s",
               TerminalInfoString(TERMINAL_DATA_PATH),OUTPUT_ROOT);
   return true;
  }

//+------------------------------------------------------------------+
//| Script entry point.                                              |
//+------------------------------------------------------------------+
void OnStart()
  {
   if(InpSymbol!=EXPECTED_SYMBOL)
     {
      PrintFormat("Sika export rejected: symbol must be exactly %s, received %s.",
                  EXPECTED_SYMBOL,InpSymbol);
      return;
     }
   if(!ValidBarCount("M15",InpM15Bars) || !ValidBarCount("H1",InpH1Bars))
      return;
   if(InpLoadTimeoutSeconds<5 || InpLoadTimeoutSeconds>120)
     {
      Print("Sika export rejected: load timeout must be between 5 and 120 seconds.");
      return;
     }
   if(!(bool)TerminalInfoInteger(TERMINAL_CONNECTED))
     {
      Print("Sika export rejected: MT5 is not connected to a trade server.");
      return;
     }
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO)
     {
      Print("Sika export rejected: v0 only permits an MT5 demo account.");
      return;
     }

   const string account_company=AccountInfoString(ACCOUNT_COMPANY);
   if(StringFind(account_company,"Exness")<0)
     {
      PrintFormat("Sika export rejected: expected an Exness account, received %s.",
                  account_company);
      return;
     }
   if(!SymbolSelect(InpSymbol,true))
     {
      PrintFormat("Sika export rejected: cannot enable %s (error=%d).",
                  InpSymbol,GetLastError());
      return;
     }

   const int digits=(int)SymbolInfoInteger(InpSymbol,SYMBOL_DIGITS);
   const double point=SymbolInfoDouble(InpSymbol,SYMBOL_POINT);
   if(digits<1 || digits>8 || !MathIsValidNumber(point) || point<=0)
     {
      PrintFormat("Sika export rejected: invalid %s price specification.",InpSymbol);
      return;
     }

   MqlTick tick;
   if(!SymbolInfoTick(InpSymbol,tick) || tick.time_msc<=0 ||
      !MathIsValidNumber(tick.bid) || !MathIsValidNumber(tick.ask) ||
      tick.bid<=0 || tick.ask<tick.bid)
     {
      PrintFormat("Sika export rejected: invalid latest %s tick (error=%d).",
                  InpSymbol,GetLastError());
      return;
     }

   MqlRates m15_rates[];
   MqlRates h1_rates[];
   if(!LoadClosedRates(PERIOD_M15,"M15",InpM15Bars,m15_rates))
      return;
   if(!LoadClosedRates(PERIOD_H1,"H1",InpH1Bars,h1_rates))
      return;

   const datetime generated_at=TimeGMT();
   const string export_id=BuildExportId(generated_at);
   ExportStats m15_stats;
   ExportStats h1_stats;
   if(!WriteRatesCsv(export_id,"M15",PERIOD_M15,digits,m15_rates,m15_stats))
      return;
   if(!WriteRatesCsv(export_id,"H1",PERIOD_H1,digits,h1_rates,h1_stats))
      return;
   WriteManifest(export_id,generated_at,digits,point,tick,m15_stats,h1_stats);
  }
