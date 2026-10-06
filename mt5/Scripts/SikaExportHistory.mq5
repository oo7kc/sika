//+------------------------------------------------------------------+
//|                                            SikaExportHistory.mq5 |
//| Resumable monthly Exness XAUUSDm M1/M15/H1 history exporter     |
//+------------------------------------------------------------------+
#property copyright "Sika"
#property version   "1.000"
#property description "Exports completed monthly XAUUSDm M1/M15/H1 bundles."
#property description "This script contains no order or position-management code."
#property script_show_inputs

input string   InpSymbol                = "XAUUSDm";
input datetime InpStartMonth            = D'2021.10.01 00:00:00';
input datetime InpEndMonthExclusive     = D'2026.10.01 00:00:00';
input int      InpLoadTimeoutSeconds    = 120;
input bool     InpOverwriteCompleted    = false;

const string EXPECTED_SYMBOL = "XAUUSDm";
const string ACCOUNT_PROFILE = "Standard";
const string PROFILE_SOURCE  = "research-contract-v0.1";
const string SCHEMA           = "sika-mt5-backfill-month-v1";
const string OUTPUT_ROOT      = "Sika\\backfill";
const int    MAX_MONTHS       = 120;

struct BarStats
  {
   string file_name;
   int    count;
   long   first_time;
   long   last_time;
   int    timeframe_seconds;
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

string JsonDouble(const double value,const int precision)
  {
   return DoubleToString(value,precision);
  }

bool IsMonthBoundary(const datetime value)
  {
   MqlDateTime parts;
   TimeToStruct(value,parts);
   return parts.day==1 && parts.hour==0 && parts.min==0 && parts.sec==0;
  }

datetime MonthStart(const datetime value)
  {
   MqlDateTime parts;
   TimeToStruct(value,parts);
   parts.day=1;
   parts.hour=0;
   parts.min=0;
   parts.sec=0;
   return StructToTime(parts);
  }

datetime NextMonth(const datetime value)
  {
   MqlDateTime parts;
   TimeToStruct(value,parts);
   parts.day=1;
   parts.hour=0;
   parts.min=0;
   parts.sec=0;
   parts.mon++;
   if(parts.mon>12)
     {
      parts.mon=1;
      parts.year++;
     }
   return StructToTime(parts);
  }

string MonthKey(const datetime value)
  {
   MqlDateTime parts;
   TimeToStruct(value,parts);
   return StringFormat("%04d%02d",parts.year,parts.mon);
  }

string MonthLabel(const datetime value)
  {
   MqlDateTime parts;
   TimeToStruct(value,parts);
   return StringFormat("%04d-%02d",parts.year,parts.mon);
  }

int CountMonths(const datetime start_month,const datetime end_month)
  {
   int count=0;
   datetime current=start_month;
   while(current<end_month && count<=MAX_MONTHS)
     {
      current=NextMonth(current);
      count++;
     }
   return count;
  }

bool ValidateEnvironment()
  {
   if(InpSymbol!=EXPECTED_SYMBOL)
     {
      PrintFormat("Sika backfill rejected: symbol must be exactly %s.",
                  EXPECTED_SYMBOL);
      return false;
     }
   if(!(bool)TerminalInfoInteger(TERMINAL_CONNECTED))
     {
      Print("Sika backfill rejected: MT5 is disconnected.");
      return false;
     }
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO)
     {
      Print("Sika backfill rejected: v0 permits demo accounts only.");
      return false;
     }

   const string server=AccountInfoString(ACCOUNT_SERVER);
   const string company=AccountInfoString(ACCOUNT_COMPANY);
   if(StringFind(server,"Exness-")!=0 || StringFind(company,"Exness")<0)
     {
      PrintFormat(
         "Sika backfill rejected: expected Exness server/company, received %s / %s.",
         server,company);
      return false;
     }
   if(!SymbolSelect(InpSymbol,true))
     {
      PrintFormat("Sika backfill cannot enable %s (error=%d).",
                  InpSymbol,GetLastError());
      return false;
     }

   const long server_time=(long)TimeTradeServer();
   const long gmt_time=(long)TimeGMT();
   if(server_time<=0 || gmt_time<=0 ||
      MathAbs((double)(server_time-gmt_time))>5.0)
     {
      PrintFormat(
         "Sika backfill rejected: Exness server clock differs from UTC by %I64d seconds.",
         server_time-gmt_time);
      return false;
     }
   return true;
  }

bool LoadMonthRates(const ENUM_TIMEFRAMES timeframe,
                    const string label,
                    const datetime month_start,
                    const datetime month_end,
                    MqlRates &rates[])
  {
   ArraySetAsSeries(rates,false);
   const ulong started=GetTickCount64();
   const ulong timeout_ms=(ulong)InpLoadTimeoutSeconds*1000;
   const datetime inclusive_end=month_end-1;
   int copied=-1;
   bool synchronized=false;

   while(!IsStopped())
     {
      ResetLastError();
      copied=CopyRates(
         InpSymbol,timeframe,month_start,inclusive_end,rates);
      synchronized=(bool)SeriesInfoInteger(
         InpSymbol,timeframe,SERIES_SYNCHRONIZED);
      if(copied>0 && synchronized)
         break;

      if(GetTickCount64()-started>=timeout_ms)
        {
         PrintFormat(
            "Sika backfill failed loading %s %s after %d seconds "
            "(copied=%d, synchronized=%s, error=%d).",
            MonthLabel(month_start),label,InpLoadTimeoutSeconds,copied,
            (synchronized ? "true" : "false"),GetLastError());
         return false;
        }
      Sleep(500);
     }

   if(IsStopped())
     {
      Print("Sika backfill cancelled by the user.");
      return false;
     }
   if(copied<=0 || ArraySize(rates)!=copied)
     {
      PrintFormat("Sika backfill received no usable %s bars for %s.",
                  label,MonthLabel(month_start));
      return false;
     }

   const int timeframe_seconds=PeriodSeconds(timeframe);
   for(int i=0;i<copied;i++)
     {
      const MqlRates row=rates[i];
      if(row.time<month_start || row.time>=month_end ||
         row.time+timeframe_seconds>TimeGMT() ||
         !MathIsValidNumber(row.open) || !MathIsValidNumber(row.high) ||
         !MathIsValidNumber(row.low)  || !MathIsValidNumber(row.close) ||
         row.open<=0 || row.high<=0 || row.low<=0 || row.close<=0 ||
         row.low>MathMin(row.open,row.close) ||
         row.high<MathMax(row.open,row.close) || row.high<row.low ||
         row.tick_volume<0 || row.real_volume<0 || row.spread<0)
        {
         PrintFormat("Sika backfill found an invalid %s bar in %s at index %d.",
                     label,MonthLabel(month_start),i);
         return false;
        }
      if(i>0 && row.time<=rates[i-1].time)
        {
         PrintFormat("Sika backfill found non-increasing %s time in %s.",
                     label,MonthLabel(month_start));
         return false;
        }
     }
   return true;
  }

bool WriteRatesCsv(const string directory,
                   const string bundle_id,
                   const string label,
                   const ENUM_TIMEFRAMES timeframe,
                   const int digits,
                   MqlRates &rates[],
                   BarStats &stats)
  {
   const string base_name=bundle_id+"_"+label+".csv";
   const string relative_path=directory+"\\"+base_name;
   ResetLastError();
   const int handle=FileOpen(
      relative_path,FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(handle==INVALID_HANDLE)
     {
      PrintFormat("Sika backfill cannot open %s (error=%d).",
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
      PrintFormat("Sika backfill failed while writing %s (error=%d).",
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

string BarJson(const BarStats &stats)
  {
   string value="{\"file\": "+JsonString(stats.file_name);
   value+=", \"count\": "+IntegerToString(stats.count);
   value+=", \"timeframe_seconds\": "+
          IntegerToString(stats.timeframe_seconds);
   value+=", \"first_time_epoch\": "+JsonLong(stats.first_time);
   value+=", \"last_time_epoch\": "+JsonLong(stats.last_time);
   value+=", \"closed_bars_only\": true}";
   return value;
  }

bool WriteManifest(const string directory,
                   const string bundle_id,
                   const string month_label,
                   const datetime month_start,
                   const datetime month_end,
                   const int digits,
                   const double point,
                   const datetime generated_at,
                   const BarStats &m1,
                   const BarStats &m15,
                   const BarStats &h1)
  {
   const long server_time=(long)TimeTradeServer();
   const long gmt_time=(long)generated_at;
   string manifest="{\n";
   manifest+="  \"schema\": "+JsonString(SCHEMA)+",\n";
   manifest+="  \"complete\": true,\n";
   manifest+="  \"mode\": \"read-only\",\n";
   manifest+="  \"bundle_id\": "+JsonString(bundle_id)+",\n";
   manifest+="  \"month\": "+JsonString(month_label)+",\n";
   manifest+="  \"requested_start_epoch\": "+
             JsonLong((long)month_start)+",\n";
   manifest+="  \"requested_end_exclusive_epoch\": "+
             JsonLong((long)month_end)+",\n";
   manifest+="  \"generated_at_epoch\": "+JsonLong(gmt_time)+",\n";
   manifest+="  \"time_basis\": {\n";
   manifest+="    \"bar_time\": \"MT5 trade-server epoch; Exness contract requires UTC\",\n";
   manifest+="    \"server_clock_source\": \"TimeTradeServer\",\n";
   manifest+="    \"server_time_epoch\": "+JsonLong(server_time)+",\n";
   manifest+="    \"server_minus_gmt_seconds\": "+
             JsonLong(server_time-gmt_time)+"\n";
   manifest+="  },\n";
   manifest+="  \"terminal\": {\n";
   manifest+="    \"name\": "+
             JsonString(TerminalInfoString(TERMINAL_NAME))+",\n";
   manifest+="    \"company\": "+
             JsonString(TerminalInfoString(TERMINAL_COMPANY))+",\n";
   manifest+="    \"build\": "+
             JsonLong(TerminalInfoInteger(TERMINAL_BUILD))+",\n";
   manifest+="    \"connected\": "+JsonBool(
      (bool)TerminalInfoInteger(TERMINAL_CONNECTED))+"\n";
   manifest+="  },\n";
   manifest+="  \"account\": {\n";
   manifest+="    \"server\": "+
             JsonString(AccountInfoString(ACCOUNT_SERVER))+",\n";
   manifest+="    \"company\": "+
             JsonString(AccountInfoString(ACCOUNT_COMPANY))+",\n";
   manifest+="    \"currency\": "+
             JsonString(AccountInfoString(ACCOUNT_CURRENCY))+",\n";
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
      SymbolInfoDouble(InpSymbol,SYMBOL_TRADE_CONTRACT_SIZE),4)+"\n";
   manifest+="  },\n";
   manifest+="  \"bars\": {\n";
   manifest+="    \"M1\": "+BarJson(m1)+",\n";
   manifest+="    \"M15\": "+BarJson(m15)+",\n";
   manifest+="    \"H1\": "+BarJson(h1)+"\n";
   manifest+="  }\n";
   manifest+="}\n";

   const string manifest_name=bundle_id+"_manifest.json";
   const string relative_path=directory+"\\"+manifest_name;
   ResetLastError();
   const int handle=FileOpen(
      relative_path,FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(handle==INVALID_HANDLE)
     {
      PrintFormat("Sika backfill cannot open manifest %s (error=%d).",
                  relative_path,GetLastError());
      return false;
     }
   const bool ok=(FileWriteString(handle,manifest)==StringLen(manifest));
   FileFlush(handle);
   FileClose(handle);
   if(!ok)
     {
      PrintFormat("Sika backfill failed writing %s (error=%d).",
                  relative_path,GetLastError());
      return false;
     }
   return true;
  }

// Returns 1 when exported, 0 when an existing complete month is skipped,
// and -1 on failure.
int ExportMonth(const datetime month_start,
                const datetime month_end,
                const int digits,
                const double point)
  {
   const string month_key=MonthKey(month_start);
   const string month_label=MonthLabel(month_start);
   const string bundle_id=month_key+"_"+InpSymbol;
   const string directory=OUTPUT_ROOT+"\\"+month_key;
   const string manifest_path=directory+"\\"+bundle_id+"_manifest.json";

   if(FileIsExist(manifest_path))
     {
      if(!InpOverwriteCompleted)
        {
         PrintFormat("Sika backfill skipped completed month %s.",month_label);
         return 0;
        }
      ResetLastError();
      if(!FileDelete(manifest_path))
        {
         PrintFormat("Sika backfill cannot clear %s (error=%d).",
                     manifest_path,GetLastError());
         return -1;
        }
     }

   PrintFormat("Sika backfill exporting %s...",month_label);
   MqlRates m1_rates[];
   MqlRates m15_rates[];
   MqlRates h1_rates[];
   if(!LoadMonthRates(PERIOD_M1,"M1",month_start,month_end,m1_rates))
      return -1;
   if(!LoadMonthRates(PERIOD_M15,"M15",month_start,month_end,m15_rates))
      return -1;
   if(!LoadMonthRates(PERIOD_H1,"H1",month_start,month_end,h1_rates))
      return -1;

   BarStats m1;
   BarStats m15;
   BarStats h1;
   if(!WriteRatesCsv(directory,bundle_id,"M1",PERIOD_M1,digits,m1_rates,m1))
      return -1;
   if(!WriteRatesCsv(directory,bundle_id,"M15",PERIOD_M15,digits,m15_rates,m15))
      return -1;
   if(!WriteRatesCsv(directory,bundle_id,"H1",PERIOD_H1,digits,h1_rates,h1))
      return -1;

   const datetime generated_at=TimeGMT();
   if(!WriteManifest(directory,bundle_id,month_label,month_start,month_end,
                     digits,point,generated_at,m1,m15,h1))
      return -1;

   PrintFormat("Sika backfill completed %s: M1=%d, M15=%d, H1=%d.",
               month_label,m1.count,m15.count,h1.count);
   return 1;
  }

void OnStart()
  {
   if(!IsMonthBoundary(InpStartMonth) ||
      !IsMonthBoundary(InpEndMonthExclusive) ||
      InpStartMonth>=InpEndMonthExclusive)
     {
      Print(
         "Sika backfill rejected: start and exclusive end must be ordered "
         "first-of-month UTC boundaries.");
      return;
     }
   if(InpEndMonthExclusive>MonthStart(TimeGMT()))
     {
      Print("Sika backfill rejected: partial current/future months are not allowed.");
      return;
     }
   const int month_count=CountMonths(InpStartMonth,InpEndMonthExclusive);
   if(month_count<1 || month_count>MAX_MONTHS)
     {
      PrintFormat("Sika backfill rejected: month count must be between 1 and %d.",
                  MAX_MONTHS);
      return;
     }
   if(InpLoadTimeoutSeconds<10 || InpLoadTimeoutSeconds>600)
     {
      Print("Sika backfill rejected: timeout must be between 10 and 600 seconds.");
      return;
     }
   if(!ValidateEnvironment())
      return;

   const int digits=(int)SymbolInfoInteger(InpSymbol,SYMBOL_DIGITS);
   const double point=SymbolInfoDouble(InpSymbol,SYMBOL_POINT);
   if(digits<1 || digits>8 || !MathIsValidNumber(point) || point<=0)
     {
      PrintFormat("Sika backfill rejected: invalid %s price specification.",
                  InpSymbol);
      return;
     }

   int exported=0;
   int skipped=0;
   datetime current=InpStartMonth;
   while(current<InpEndMonthExclusive && !IsStopped())
     {
      const datetime next=NextMonth(current);
      const int result=ExportMonth(current,next,digits,point);
      if(result<0)
        {
         PrintFormat(
            "Sika history backfill stopped at %s. Completed earlier months remain usable.",
            MonthLabel(current));
         return;
        }
      if(result==0)
         skipped++;
      else
         exported++;
      current=next;
     }

   if(IsStopped())
     {
      Print("Sika history backfill cancelled; rerun to resume.");
      return;
     }
   PrintFormat(
      "Sika history backfill complete: months=%d, exported=%d, skipped=%d.",
      month_count,exported,skipped);
   PrintFormat("Backfill root: %s\\MQL5\\Files\\%s",
               TerminalInfoString(TERMINAL_DATA_PATH),OUTPUT_ROOT);
  }
