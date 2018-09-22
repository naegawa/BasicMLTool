import pickle
import os
import argparse
import random
import numpy as np
import warnings
from multiprocessing import Pool
with warnings.catch_warnings():
	warnings.simplefilter("ignore")
	from sklearn.ensemble import RandomForestClassifier
	from sklearn.feature_selection import SelectFromModel
	from sklearn.feature_selection import RFE,RFECV
	from sklearn import svm
	import sklearn
import csv
import json

# this project
from util import load_data,NumPyArangeEncoder

#############################################################################
# 識別のためのモデルとグリッドサーチのためのパラメータを返す　　　　　　　　#
#############################################################################
def get_classifier_model(args):
	if args.model=="rf":
		param_grid = {
			'n_estimators'      : [10, 100, 1000],
			'max_features'      : ['auto'],
			'min_samples_split' : [2],
			'max_depth'         : [None],
			}
		clf = RandomForestClassifier()
	elif args.model=="svm":
		param_grid={
			'C': np.linspace(0.0001, 10, num = args.trials)
			}
		clf = svm.SVC(kernel = 'linear',probability=True)
	elif args.model=="rbf_svm":
		param_grid={
			'C':np.linspace(0.0001, 10, num = args.trials),
			'gamma':np.linspace(0.01, 100, num = args.trials)
			}
		clf = svm.SVC(kernel = 'rbf',probability=True)
	elif args.model=="lr":
		param_grid={
			'C':np.linspace(0.0001, 10, num = args.trials),
			}
		clf = sklearn.linear_model.LogisticRegression()
	return clf,param_grid
	
################################################
# 評価を行う　　　　　　　                  　 #
# test_y:テストデータの正答　　　　　　　　    #
# pred_y:予測結果　　　　　　　　              #
# prob_y:予測スコア　　　　　　　　            #
# result:評価結果を保存するためのディクショナリ#
################################################
def evaluate(test_y,pred_y,prob_y,result={}):
	if prob_y.shape[1]==2:
		## ２値分類
		auc = sklearn.metrics.roc_auc_score(test_y,prob_y[:,1],average='macro')
		roc_curve = sklearn.metrics.roc_curve(test_y,prob_y[:,1],pos_label=1)
		result["roc_curve"]=roc_curve
		result["auc"]=auc.tolist()
		precision, recall, f1, support=sklearn.metrics.precision_recall_fscore_support(test_y,pred_y)
		result["precision"]=precision
		result["recall"]=precision
		result["f1"]=f1
		conf=sklearn.metrics.confusion_matrix(test_y, pred_y)
		result["confusion"]=conf
	else:
		## 多値分類
		result["roc_curve"]=[]
		result["auc"]=[]
		for i in range(prob_y.shape[1]):
			auc = sklearn.metrics.roc_auc_score(test_y==i,prob_y[:,i],average='macro')
			roc_curve = sklearn.metrics.roc_curve(test_y==i,prob_y[:,i],pos_label=1)
			result["roc_curve"].append(roc_curve)
			result["auc"].append(auc.tolist())
		precision, recall, f1, support=sklearn.metrics.precision_recall_fscore_support(test_y,pred_y,average='macro')
		result["precision"]=precision
		result["recall"]=precision
		result["f1"]=f1
		conf=sklearn.metrics.confusion_matrix(test_y, pred_y)
		result["confusion"]=conf
	accuracy = sklearn.metrics.accuracy_score(test_y,pred_y)
	result["accuracy"]=accuracy
	return result

################################################
# cross-validation の1 fold 分の計算           #
################################################
def train_cv_one_fold(arg):
	x,y,h,one_kf=arg
	##
	## 学習用セットとテスト用セットに分ける
	##
	train_idx, test_idx = one_kf
	train_x=x[train_idx]
	train_y=y[train_idx]
	test_x=x[test_idx]
	test_y=y[test_idx]
	##
	## 手法を選択
	##
	clf, param_grid = get_classifier_model(args)
	# clf が学習済みかどうかを表すフラグ
	fitted=False
	result={}
	##
	## 特徴選択を行う
	##
	selected_feature=None
	if args.feature_selection:
		##
		## 特徴選択を行い、選択された特徴で予測をする
		##
		rfe = RFECV(clf)
		rfe = rfe.fit(train_x, train_y)
		pred_y = rfe.predict(test_x)
		prob_y = rfe.predict_proba(test_x)
		result["test_y"]=test_y.tolist()
		result["pred_y"]=pred_y.tolist()
		result["prob_y"]=prob_y.tolist()
		##
		## 選択された特徴を保存する
		##
		selected_feature=rfe.support_
		print("=== selected feature ===")
		if h is None:
			print([i  for i,el in enumerate(selected_feature) if el==True])
		else:
			print([attr  for attr,el in zip(h,selected_feature) if el==True])
		result["selected_feature"]=selected_feature
		##
		## 学習・テストデータをこのfold中、選択された特徴のみにする
		##
		fitted=True
		train_x=train_x[:,selected_feature]
		test_x=test_x[:,selected_feature]
	

	if args.grid_search:
		##
		## グリッドサーチでハイパーパラメータを選択する
		## ハイパーパラメータを評価するため学習セットを、さらに、パラメータを決定する学習セットとハイパーパラメータを評価するためのバリデーションセットに分けてクロスバリデーションを行う
		##
		grid_search = sklearn.model_selection.GridSearchCV(clf, param_grid, cv=args.param_search_splits)
		grid_search.fit(train_x,train_y)
		
		##
		## 最も良かったハイパーパラメータのモデルを用いてテストデータで評価を行う
		##
		pred_y = grid_search.predict(test_x)
		prob_y = grid_search.predict_proba(test_x)
		##
		## 最も良かったハイパーパラメータや結果を保存
		##
		print('Best parameters: {}'.format(grid_search.best_params_))
		print('Best cross-validation: {}'.format(grid_search.best_score_))
		result={
			"param":grid_search.best_params_,
			"best_score":grid_search.best_score_,
			"test_y":test_y.tolist(),
			"pred_y":pred_y.tolist(),
			"prob_y":prob_y.tolist(),
			}
		##
		## 最も良かったハイパーパラメータの識別器を保存
		## （学習データ全体での再フィッティングはこの段階では行わない）
		##
		clf=grid_search.best_estimator_
		fitted=False

	##
	## clf が学習済みでなければ、学習データ全体で学習する
	##
	if not fitted:
		clf.fit(train_x,train_y)
		pred_y = clf.predict(test_x)
		prob_y = clf.predict_proba(test_x)
		result["test_y"]=test_y.tolist()
		result["pred_y"]=pred_y.tolist()
		result["prob_y"]=prob_y.tolist()
	##
	## 評価
	##
	result=evaluate(test_y,pred_y,prob_y,result)
	print("Cross-validation accuracy: %3f"%(result["accuracy"]))
	return result


##############################################
# --- 学習処理の全体                     --- #
##############################################
def run_train(args):
	all_result={}
	for filename in args.input_file:
		print("=================================")
		print("== Loading data ... ")
		print("=================================")
		x,y,h=load_data(filename,ans_col=args.answer,ignore_col=args.ignore,header=args.header)
		print("x:",x.shape)
		print("y:",y.shape)
		
		##
		## cross-validation を並列化して行う
		##
		print("=================================")
		print("== Starting cross-validation ... ")
		print("=================================")
		kf=sklearn.model_selection.KFold(n_splits=args.splits, shuffle=True)
		pool = Pool(processes=args.splits)
		results = pool.map(train_cv_one_fold, [(x,y,h,s)for s in kf.split(x)])

		##
		## cross-validation の結果をまとめる
		## ・各評価値の平均・標準偏差を計算する
		##
		cv_result={"cv": results}
		print("=================================")
		print("== Evaluation ... ")
		print("=================================")
		for score_name in ["accuracy","f1","precision","recall","auc"]:
			scores=[r[score_name] for r in results]
			test_mean = np.nanmean(np.asarray(scores))
			test_std = np.nanstd(np.asarray(scores))
			print("Mean %10s on test set: %3f (standard deviation: %3s)"
				% (score_name,test_mean,test_std))
			cv_result[score_name+"_mean"]=test_mean
			cv_result[score_name+"_std"]=test_std
		##
		## 全体の評価
		##
		test_y=[]
		pred_y=[]
		for result in cv_result["cv"]:
			test_y.extend(result["test_y"])
			pred_y.extend(result["pred_y"])
		conf=sklearn.metrics.confusion_matrix(test_y, pred_y)
		cv_result["confusion"]=conf
		##
		## 結果をディクショナリに保存して返値とする
		##
		all_result[filename]=cv_result
	return all_result


############################################################
# --- mainの関数：コマンド実行時にはここが呼び出される --- #
############################################################
if __name__ == '__main__':
	##
	## コマンドラインのオプションの設定
	##
	parser = argparse.ArgumentParser(description = "Classification")
	parser.add_argument("--grid_search",default=False,
		help = "enebled grid search", action="store_true")
	parser.add_argument("--feature_selection",default=False,
		help = "enabled feature selection", action="store_true")
	parser.add_argument("--input_file","-f",nargs='+',default=None,
		help = "input filename (txt/tsv/csv)", type = str)
	parser.add_argument("--trials",default=3,
		help = "Trials for hyperparameters random search", type = int)
	parser.add_argument("--splits","-s", default=5,
		help = "number of splits for cross validation", type = int)
	parser.add_argument("--param_search_splits","-p", default=3,
		help = "number of splits for parameter search", type = int)
	parser.add_argument('--header','-H',default=False,
		help = "number of splits", action='store_true')
	parser.add_argument('--answer','-A',
		help = "column number of answer label", type=int)
	parser.add_argument('--ignore','-I',nargs='*',default=[],
		help = "column numbers for ignored data", type=int)
	parser.add_argument("--model",default="rf",
		help = "methods(rf/svm)", type = str)
	parser.add_argument('--output_json',default=None,
		help = "output: json", type=str)
	parser.add_argument('--output_csv',default=None,
		help = "output: csv", type=str)
	
	##
	## コマンドラインのオプションによる設定はargsに保存する
	##
	args = parser.parse_args()
	##
	## 乱数初期化
	##
	np.random.seed(20) 

	##
	## 学習開始
	##
	all_result=run_train(args)
	##
	## 結果を簡易に表示
	##
	metrics=["accuracy","auc"]
	print("=================================")
	print("== summary ... ")
	print("=================================")
	metrics_names=sorted([m+"_mean" for m in metrics]+[m+"_std" for m in metrics])
	print("\t".join(["filename"]+metrics_names))
	for key,o in all_result.items():
		arr=[key]
		for name in metrics_names:
			arr.append("%2.4f"%(o[name],))
		print("\t".join(arr))
		
	##
	## 結果をjson ファイルに保存
	## 予測結果やcross-validationなどの細かい結果も保存される
	##
	if args.output_json:
		print("[SAVE]",args.output_json)
		fp = open(args.output_json, "w")
		json.dump(all_result,fp, indent=4, cls=NumPyArangeEncoder)
	
	##
	## 結果をcsv ファイルに保存
	##
	if args.output_csv:
		print("[SAVE]",args.output_csv)
		fp = open(args.output_csv, "w")
		metrics= ["accuracy","f1","precision","recall","auc"]
		metrics_names=sorted([m+"_mean" for m in metrics]+[m+"_std" for m in metrics])
		fp.write("\t".join(["filename"]+metrics_names))
		fp.write("\n")
		for key,o in all_result.items():
			arr=[key]
			for name in metrics_names:
				arr.append("%2.4f"%(o[name],))
			fp.write("\t".join(arr))
			fp.write("\n")
		