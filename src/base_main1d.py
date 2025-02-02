from operation import RangeSelection, TupleUpdateType
from tqdm import tqdm
import time
import warnings
import black_box
import json
import sys
from error_metrics import get_average_q_error
from connection import get_connection
from pg_hint_utility import gen_final_hint, inject_single_table_sels_and_get_cost, get_real_latency, get_single_table_pointer

warnings.filterwarnings("ignore")

def load_trainingset(
    trainingset_filename, n_tabs, tabs_for_model, sel_cols, pgtypes
):
    print("Load Trainingset")
    with open(trainingset_filename, "r") as fin:
        tab_to_training_set = {}
        for tab in tabs_for_model:
            tab_to_training_set[tab] = []

        lines = list(fin.readlines())

        for i in range(len(lines)):
            row = lines[i].strip().split(",")
            for j in range(n_tabs):
                if row[1 + j] in tabs_for_model:
                    tab = row[1 + j]
                    lb_id = 1 + n_tabs + 2 * j
                    ub_id = lb_id + 1
                    card_id = 1 + n_tabs * 3 + j

                    _col = list(sel_cols[tab].keys())[0]

                    if (
                        int(row[card_id]) >= 1
                        and len(tab_to_training_set[tab]) < black_box.queries
                    ):
                        if "/" in _col:
                            lb, ub = float(row[lb_id]), float(row[ub_id])
                        elif pgtypes[tab][_col].lower() == "real" or pgtypes[tab][_col].lower().startswith("decimal"):
                            lb, ub = float(row[lb_id]), float(row[ub_id])
                        elif pgtypes[tab][_col].lower() == "integer":
                            lb, ub = int(row[lb_id]), int(row[ub_id])
                        else:
                            raise NotImplementedError
                        tab_to_training_set[tab].append((lb, ub, int(row[card_id])))

        print("Finish loading training set:")
        for tab in tab_to_training_set:
            print(f"Training set size of [{tab}]: {len(tab_to_training_set[tab])}")
            tab_abbrev = "".join(x[0] for x in tab.strip().split("_"))
            black_box.retrain(
                tab,
                [f"{tab} {tab_abbrev}"],
                [""],
                tab_to_training_set[tab],
            )

def load_log(
    conn,
    cursor,
    sql,
    cur_table_sizes,
    log_filename,
    output_prefix,
    n_tabs,
    sel_cols,
    tabs_for_model,
    pgtypes,
    tab_to_alias,
    disable_table_with_sel_insertions_in_batch,
):
    print("Load Log")

    tab_to_info_id = {}
    tab_to_pointer = {}
    for i in range(len(tabs_for_model)):
        tab_to_info_id[tabs_for_model[i]] = i + 1

    for tab in tabs_for_model:
        assert len(sel_cols[tab]) == 1
        _col = list(sel_cols[tab].keys())[0]
        single_table_to_qid = get_single_table_pointer(
            sql=sql.replace(
                "{lb" + str(tab_to_info_id[tab]) + "}", 
                str(sel_cols[tab][_col]["min"])
            ).replace(
                "{ub" + str(tab_to_info_id[tab]) + "}", 
                str(sel_cols[tab][_col]["max"])
            )
        )
        if tab in tab_to_alias:
            assert tab_to_alias[tab] in single_table_to_qid
            tab_to_pointer[tab] = single_table_to_qid[tab_to_alias[tab]]
        else:
            assert tab in single_table_to_qid
            tab_to_pointer[tab] = single_table_to_qid[tab]

    to_insert_buffer = []
    to_delete_range = [None, None]

    last_op_type = None
    last_tab = None

    n_tabs_in_from = sql.lower().split("from")[1].split("where")[0].count(",") + 1

    with open(log_filename, "r") as fin, open(
        output_prefix + "_answer.txt", "w"
    ) as fout:
        for row_num, line in enumerate(tqdm(fin)):
            op_type = line[0]
            if op_type == "Q":
                tab = None
            else:
                tab = line.split(",")[1]

            # we flush the tuple updates for tables
            if (last_op_type != op_type or last_tab != tab) and (last_op_type != "Q"):
                if last_op_type == "I" and len(to_insert_buffer) > 0:
                    cursor.execute(f"insert into {last_tab} ({', '.join(list(pgtypes[last_tab].keys()))}) values " + ','.join([x.decode('utf-8') for x in to_insert_buffer]))
                    # print(f"flush {len(to_insert_buffer)} insertions to {last_tab}")
                    to_insert_buffer = []
                if last_op_type == "D" and to_delete_range[0] is not None:
                    cursor.execute(f"delete from {last_tab} where row_id >= {to_delete_range[0]} and row_id <= {to_delete_range[1]};")
                    # print(f"flush {to_delete_range[1] - to_delete_range[0] + 1} deletions to {last_tab}")
                    to_delete_range = [None, None]
            if last_op_type != "Q" and op_type == "Q":
                cursor.execute("vacuum (full, analyze);")
            last_op_type, last_tab = op_type, tab

            start_ts = time.time()
            ret = str(row_num) + ":"
            if op_type in ["I", "D"]:
                _type = TupleUpdateType.from_str(line.split(",")[0])
                t = line.split(",")[1]
                assert t == tab
                field = line[2 + len(t) + 1 :].strip()
                if disable_table_with_sel_insertions_in_batch and t in tabs_for_model:
                    if _type == TupleUpdateType.INSERT:
                        cur_table_sizes[tab] += 1
                        attr_vals = []
                        for x in field.split(","):
                            if x == "None":
                                attr_vals.append(None)
                            else:
                                attr_vals.append(x)
                        attr_vals = tuple(attr_vals)
                        insert_command = (
                            f"insert into {t} ("
                            + ",".join(pgtypes[t])
                            + ") values ("
                            + ",".join(['%s'] * len(pgtypes[t]))
                            + f");"
                        )
                        cursor.execute(insert_command, attr_vals)
                    elif _type == TupleUpdateType.DELETE:
                        cur_table_sizes[tab] -= 1
                        delete_command = f"delete from {t} where row_id = {int(field)};"
                        cursor.execute(delete_command)
                else:
                    if _type == TupleUpdateType.INSERT:
                        cur_table_sizes[tab] += 1
                        attr_vals = []
                        for x in field.split(","):
                            if x == "None":
                                attr_vals.append(None)
                            else:
                                attr_vals.append(x)
                        attr_vals = tuple(attr_vals)
                        to_insert_buffer.append(cursor.mogrify("(" + ",".join(['%s'] * len(pgtypes[t])) + ")", attr_vals))
                    elif _type == TupleUpdateType.DELETE:
                        cur_table_sizes[tab] -= 1
                        row_id = int(field)
                        if to_delete_range[0] is None or to_delete_range[0] > row_id:
                            to_delete_range[0] = row_id
                        if to_delete_range[1] is None or to_delete_range[1] < row_id:
                            to_delete_range[1] = row_id
                ret += f"time={round(time.time() - start_ts, 6):.6f}"
            elif op_type == "Q":
                row = line.strip().split(",")
                for jj in range(n_tabs):
                    if row[1 + jj] in tabs_for_model:
                        tab = row[1 + jj]
                        tab_abbrev = "".join(x[0] for x in tab.strip().split("_"))
                        info_id = tab_to_info_id[tab]

                        lb_id = 1 + n_tabs + 2 * jj
                        ub_id = lb_id + 1
                        card_id = 1 + n_tabs * 3 + jj
                        _col = list(sel_cols[tab].keys())[0]
                        if "/" in _col:
                            lb, ub = float(row[lb_id]), float(row[ub_id])
                        elif pgtypes[tab][_col].lower() == "real" or pgtypes[tab][_col].lower().startswith("decimal"):
                            lb, ub = float(row[lb_id]), float(row[ub_id])
                        elif pgtypes[tab][_col].lower() == "integer":
                            lb, ub = int(row[lb_id]), int(row[ub_id])
                        else:
                            raise NotImplementedError
                        true_card = int(row[card_id])

                        rs = RangeSelection(tab, lb, ub)
                        rs.update_by(
                            sel_cols[tab][_col]["min"], sel_cols[tab][_col]["max"]
                        )

                        base_start_ts = time.time()
                        est = black_box.predict_one(
                            tab,
                            [rs.lb, rs.ub],
                            [f"{tab} {tab_abbrev}"],
                            [""],
                        )
                        base_time = time.time() - base_start_ts

                        q = sql.replace("{lb" + str(info_id) + "}", str(rs.lb)).replace("{ub" + str(info_id) + "}", str(rs.ub))

                        # inject the "est" and get the plan info
                        _, join_order, scan_mtd = inject_single_table_sels_and_get_cost(
                            pointer=tab_to_pointer[tab],
                            sel=est / cur_table_sizes[tab],
                            n_tabs_in_from=n_tabs_in_from,
                            q=q,
                            hint=None,
                            plan_info=True,
                        ) 
                        # construct the plan by the info
                        hint = gen_final_hint(scan_mtd=scan_mtd, str=join_order)
                        # we use the "true_card" to cost the plan
                        plan_cost = inject_single_table_sels_and_get_cost(
                            pointer=tab_to_pointer[tab],
                            sel=true_card / cur_table_sizes[tab],
                            n_tabs_in_from=n_tabs_in_from,
                            q = q,
                            hint=hint,
                            plan_info=False,
                        )
                        # lets run it!
                        _, execution_time, _  = get_real_latency(
                            sql=q,
                            hint=hint,
                        )

                        execution_time = execution_time / 1000.
            
                        ret += f"est{info_id}=" + str(est)
                        ret += f",observed_err{info_id}={round(get_average_q_error([true_card], [est]), 6):.6f}"
                        ret += f",plan_cost{info_id}={plan_cost}"
                        ret += f",execution_time{info_id}={round(execution_time, 6):.6f}"
                        ret += f",base_time{info_id}={round(base_time, 6):.6f}"
                        ret += f",time{info_id}={round(time.time() - start_ts, 6):.6f}"

                        hint_wo_newline = hint.replace('\n', '')
                        ret += f",plan{info_id}={hint_wo_newline}"
            else:
                raise NotImplementedError
            fout.write(ret + "\n")

def load_table(conn, cursor, table_name, file, jk_cols, sel_cols, pgtypes, timestamp_col=None):
    cursor.execute(f"drop table if exists {table_name};")
    for jk_col in jk_cols:
        cursor.execute(f"drop index if exists idx_{table_name}_{jk_col};")
    for sel_col in sel_cols:
        if " " in sel_col:
            for each in sel_col.split(" "):
                if each.startswith(table_name[0]): # share the same first bit as the table_name
                    cursor.execute(f"drop index if exists idx_{table_name}_{each};")
        else:
            cursor.execute(f"drop index if exists idx_{table_name}_{sel_col};")

    fake_table_name = "fake_" + table_name
    q = f"create table {fake_table_name} ("
    q += ", ".join(k + " " + v for k, v in pgtypes.items())
    q += ");"
    cursor.execute(q)
    q = f"copy {fake_table_name} from stdin delimiter ',' csv header"
    cursor.copy_expert(q, open(file, "r"))

    q = f"create table {table_name} ("
    q += "row_id serial, "
    q += ", ".join(k + " " + v for k, v in pgtypes.items())
    q += ");"
    cursor.execute(q)

    q = f"insert into {table_name} select nextval('{table_name}_row_id_seq'), * from {fake_table_name}"
    if timestamp_col is not None:
        q += f" order by {timestamp_col} asc;"
    cursor.execute(q)
    cursor.execute(f"drop table if exists {fake_table_name};")

    for jk_col in jk_cols:
        cursor.execute(
            f"create index idx_{table_name}_{jk_col} on {table_name}({jk_col});"
        )
    for sel_col in sel_cols:
        if " " in sel_col:
            for each in sel_col.split(" "):
                if each.startswith(table_name[0]): # share the same first bit as the table_name
                    cursor.execute(f"create index idx_{table_name}_{each} on {table_name}({each});")
        else:
            cursor.execute(
                f"create index idx_{table_name}_{sel_col} on {table_name}({sel_col});"
            )

    cursor.execute(f"select count(*) from {table_name};")
    return cursor.fetchone()[0]

if __name__ == "__main__":
    json_filename = sys.argv[1]
    with open(json_filename, "r") as json_fin:
        config = json.load(json_fin)
        tabs = config["tables"]
        if "static_tables" in config:
            static_tabs = config["static_tables"]
        else:
            static_tabs = []
        sel_cols = config["sel_cols"]
        jk_cols=config["jk_cols"]
        timestamp_cols=config["timestamp_cols"]
        sql = config["sql"]
        pgtypes = config["pgtypes"]
        debug = config["debug"]
        if "disable_table_with_sel_insertions_in_batch" in config:
            disable_table_with_sel_insertions_in_batch = config["disable_table_with_sel_insertions_in_batch"]
        else:
            disable_table_with_sel_insertions_in_batch = False
        table_filenames = config["table_filenames"]
        log_filename = config["log_filename"]
        trainingset_filename = config["trainingset_filename"]
        output_prefix = config["output_prefix"]
        if debug:
            output_prefix = "/".join(output_prefix.split("/")[:-1]) + "/test"
        else:
            output_prefix += f"_no-retraining_no-cache"

        # get db connection
        conn, cursor = get_connection()

        cur_table_sizes = {}
        # load static tables
        for static_tab in static_tabs:
            cur_table_sizes[static_tab] = load_table(
                conn=conn,
                cursor=cursor,
                table_name=static_tab,
                file=table_filenames[static_tab],
                jk_cols=jk_cols[static_tab],
                sel_cols={},
                pgtypes=pgtypes[static_tab],
                timestamp_col=None,
            )


        # we only need to build model for tables with selections
        tabs_for_model = list(sel_cols.keys())
        tab_to_alias = {}
        for ii in range(len(tabs)):
            if (" " in tabs[ii] or "as" in tabs[ii]):
                # there is an alias name
                _tab = tabs[ii].split(" ")[0]
                tab_to_alias[_tab] = tabs[ii].split(" ")[-1]
                tabs[ii] = _tab
            tab = tabs[ii]
            cur_table_sizes[tab] = load_table(
                conn=conn,
                cursor=cursor,
                table_name=tab,
                file=table_filenames[tab],
                jk_cols=jk_cols[tab],
                sel_cols=sel_cols[tab] if tab in sel_cols else {},
                pgtypes=pgtypes[tab],
                timestamp_col=timestamp_cols[tab],
            )

        # analyze
        cursor.execute("vacuum (full, analyze);")
        
        # setup the black box
        for tab in sel_cols:
            tab_abbrev = "".join(x[0] for x in tab.strip().split("_"))
            black_box.default_column_min_max_vals[tab] = {}
            for col in sel_cols[tab]:
                black_box.default_column_min_max_vals[tab][tab_abbrev + "." + col] = [
                    sel_cols[tab][col]["min"],
                    sel_cols[tab][col]["max"],
                ]
            black_box.default_predicate_templates[tab] = []
            for col in sel_cols[tab]:
                black_box.default_predicate_templates[tab].append(
                    tab_abbrev + "." + col
                )
                black_box.default_predicate_templates[tab].append(">")
                black_box.default_predicate_templates[tab].append("")
                black_box.default_predicate_templates[tab].append(
                    tab_abbrev + "." + col
                )
                black_box.default_predicate_templates[tab].append("<")
                black_box.default_predicate_templates[tab].append("")

        load_trainingset(
            trainingset_filename=trainingset_filename,
            n_tabs=len(tabs),
            tabs_for_model=tabs_for_model,
            sel_cols=sel_cols,
            pgtypes=pgtypes,
        )

        load_log(
            conn=conn,
            cursor=cursor,
            sql=sql,
            cur_table_sizes=cur_table_sizes,
            log_filename=log_filename,
            output_prefix=output_prefix,
            n_tabs=len(tabs),
            sel_cols=sel_cols,
            tabs_for_model=tabs_for_model,
            pgtypes=pgtypes,
            tab_to_alias=tab_to_alias,
            disable_table_with_sel_insertions_in_batch=disable_table_with_sel_insertions_in_batch,
        )
